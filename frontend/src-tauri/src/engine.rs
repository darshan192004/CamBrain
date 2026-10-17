//! Supervised engine child (D6-1 of phase-6-packaging.md).
//!
//! The shell spawns `uvicorn app.main:app` as a child process and restarts it
//! while the shell lives: exit -> exponential backoff (1s doubling, capped
//! 60s, jittered; a stable run of STABLE_RUN_S resets the ladder) -> respawn.
//! Every transition is appended to `<LOCALAPPDATA>\CamBrain\logs\engine.log`
//! so the installer's support path can read what the engine did.
//!
//! D6-10: this module owns no business logic. It knows how to start, watch,
//! and kill one process over HTTP-localhost, nothing more.

use std::io::Write;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::time::{Duration, Instant};

use chrono::Local;

/// Set when the operator quits the shell: the supervisor must not respawn.
static SHUTDOWN: AtomicBool = AtomicBool::new(false);
/// PID of the live engine child, for the tray's "Restart service".
static ENGINE_PID: AtomicU32 = AtomicU32::new(0);
const BACKOFF_CAP_S: u64 = 60;
const STABLE_RUN_S: u64 = 60;
/// CREATE_NO_WINDOW: a console engine in a GUI shell pops a console window.
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Call on shell shutdown: the supervisor stops respawning.
pub fn mark_shutdown() {
    SHUTDOWN.store(true, Ordering::SeqCst);
}

/// Kill the current engine child (tray "Restart service"/"Quit"). Harmless if
/// the engine is down; the supervisor reacts to the death like any other.
pub fn kill_child() {
    let pid = ENGINE_PID.swap(0, Ordering::SeqCst);
    if pid == 0 {
        return;
    }
    let mut kill = Command::new("taskkill");
    kill.args(["/PID", &pid.to_string(), "/F", "/T"]).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        kill.creation_flags(CREATE_NO_WINDOW);
    }
    let _ = kill.spawn().map(|mut k| k.wait());
}

struct EngineEnv {
    cmd: String,
    cwd: PathBuf,
    logs: PathBuf,
}

fn engine_env() -> EngineEnv {
    EngineEnv {
        cmd: std::env::var("CAMBRAIN_ENGINE_CMD").unwrap_or_else(|_| {
            "python -m uvicorn app.main:app --host 127.0.0.1 --port 8765".into()
        }),
        cwd: std::env::var("CAMBRAIN_ENGINE_CWD")
            .map(PathBuf::from)
            .unwrap_or_else(|_| {
                // Dev layout: the manifest dir is src-tauri, so <repo>/backend.
                PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("backend")
            }),
        logs: appdata().join("logs"),
    }
}

fn spawn_child(env: &EngineEnv) -> std::io::Result<Child> {
    let mut parts = env.cmd.split_whitespace();
    let program = parts
        .next()
        .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::InvalidInput, "empty engine cmd"))?;
    let mut command = Command::new(program);
    // uvicorn logs to stderr; send it to the engine log (append) so the
    // installer's support path can read what the engine said. The lifecycle
    // lines from log() share the file.
    let engine_log = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(env.logs.join("engine.log"))
        .map(Stdio::from)
        .unwrap_or(Stdio::null());
    command
        .args(parts)
        .current_dir(&env.cwd)
        // D6-3: the packaged app writes under %LOCALAPPDATA%\CamBrain. The
        // backend's config defaults are literal "%LOCALAPPDATA%\..." strings
        // that never expand, so the shell must pass resolved paths — but an
        // explicitly inherited CAMBRAIN_* (dev, tests, integrators) wins.
        // CAMBRAIN_RUNTIME_ENABLED unset means the packaged default: on.
        .stdout(Stdio::null())
        .stderr(engine_log);
    for (key, resolved) in [
        ("CAMBRAIN_DB_PATH", appdata().join("cambrain.db")),
        ("CAMBRAIN_MEDIA_ROOT", appdata().join("media")),
        ("CAMBRAIN_RUNTIME_ENABLED", PathBuf::from("1")),
    ] {
        if std::env::var_os(key).is_none() {
            command.env(key, resolved);
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW: a console engine in a GUI shell pops a console.
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command.spawn()
}

/// Spawn the supervisor thread. Returns immediately; the thread owns the
/// engine child for the life of the shell.
pub fn supervise() {
    let env = engine_env();
    std::thread::spawn(move || {
        let _ = std::fs::create_dir_all(&env.logs);
        let mut attempt: u32 = 0;
        while !SHUTDOWN.load(Ordering::SeqCst) {
            let started = Instant::now();
            let mut child = match spawn_child(&env) {
                Ok(child) => child,
                Err(err) => {
                    log(&env, &format!("spawn failed: {err}"));
                    attempt += 1;
                    sleep_backoff(attempt);
                    continue;
                }
            };
            ENGINE_PID.store(child.id(), Ordering::SeqCst);
            log(&env, &format!("engine started (pid {})", child.id()));
            match child.wait() {
                Ok(status) => log(&env, &format!("engine exited: {status}")),
                Err(err) => log(&env, &format!("engine wait failed: {err}")),
            }
            ENGINE_PID.store(0, Ordering::SeqCst);
            if started.elapsed() >= Duration::from_secs(STABLE_RUN_S) {
                attempt = 0; // a stable run resets the backoff ladder
            }
            attempt += 1;
            sleep_backoff(attempt);
        }
        log(&env, "supervisor stopped");
    });
}

fn sleep_backoff(attempt: u32) {
    if SHUTDOWN.load(Ordering::SeqCst) {
        return;
    }
    let exp = 1u64 << attempt.min(6); // 1, 2, 4 ... 64
    let secs = exp.min(BACKOFF_CAP_S);
    let jitter = u64::from(Instant::now().elapsed().subsec_millis()) % 250;
    std::thread::sleep(Duration::from_secs(secs) + Duration::from_millis(jitter));
}

fn appdata() -> PathBuf {
    let base = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| ".".into());
    PathBuf::from(base).join("CamBrain")
}

fn log(env: &EngineEnv, text: &str) {
    let path = env.logs.join("engine.log");
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let stamp = Local::now().format("%Y-%m-%dT%H:%M:%S%.3f");
        let _ = writeln!(file, "{stamp} {text}");
    }
}
