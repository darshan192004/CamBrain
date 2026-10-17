//! Single instance (D6-7): named mutex + pid file.
//!
//! Replaces the single-instance plugin on this toolchain: the plugin's
//! hidden message window never materialised (windows-gnu 1.99; evidence in
//! the phase-6 ledger), and without it the second instance runs a duplicate
//! engine that crash-loops on the bind port. The mutex is OS-guaranteed and
//! released by the OS when the process dies.

use std::io::Write;
use std::path::PathBuf;

use windows_sys::Win32::Foundation::{ERROR_ALREADY_EXISTS, GetLastError, HANDLE};
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    AllowSetForegroundWindow, FindWindowW, SetForegroundWindow, ShowWindow, SW_RESTORE, SW_SHOW,
};

const MUTEX_NAME: &str = "CamBrainShellSingleInstanceMutex";
const WINDOW_CLASS: &str = "Tauri Window";
const WINDOW_TITLE: &str = "CamBrain";

pub enum Instance {
    /// Owns the mutex; runs the shell.
    Primary,
    /// Another shell already runs; HWND of its main window (null = not found).
    Secondary(HANDLE),
}

fn appdata() -> PathBuf {
    let base = std::env::var("LOCALAPPDATA").unwrap_or_else(|_| ".".into());
    PathBuf::from(base).join("CamBrain")
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// Acquire the instance role.
///
/// The primary never closes its mutex handle: the OS releases it when the
/// process dies, which is exactly the semantic we want — releasing before
/// exit would let a second shell race a dying first one.
pub fn acquire() -> Instance {
    let name = wide(MUTEX_NAME);
    // The handle is never closed: the OS keeps the mutex alive until the
    // process dies, which is exactly the semantic we want — closing it (or
    // releasing) before exit would let a second shell race a dying first one.
    let _handle = unsafe { CreateMutexW(std::ptr::null(), 1, name.as_ptr()) };
    if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
        let pid = std::fs::read_to_string(appdata().join("shell.pid"))
            .ok()
            .and_then(|text| text.trim().parse::<u32>().ok())
            .unwrap_or(0);
        if pid != 0 {
            // Hand over the right to foreground its window before this
            // process exits (Windows forbids the new process to set another
            // process's window to the foreground without this grant).
            unsafe { AllowSetForegroundWindow(pid) };
        }
        let (class, title) = (wide(WINDOW_CLASS), wide(WINDOW_TITLE));
        let hwnd = unsafe { FindWindowW(class.as_ptr(), title.as_ptr()) };
        return Instance::Secondary(hwnd);
    }
    let _ = std::fs::create_dir_all(appdata());
    if let Ok(mut file) = std::fs::File::create(appdata().join("shell.pid")) {
        let _ = writeln!(file, "{}", std::process::id());
    }
    Instance::Primary
}

/// Raise the first instance's main window.
pub fn focus_running(hwnd: HANDLE) {
    if hwnd.is_null() {
        return;
    }
    unsafe {
        ShowWindow(hwnd, SW_RESTORE);
        ShowWindow(hwnd, SW_SHOW);
        SetForegroundWindow(hwnd);
    }
}
