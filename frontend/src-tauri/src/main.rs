// Prevent an extra console window on Windows release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod engine;

fn main() {
    // D6-1: the shell supervises the engine; the engine does the work.
    engine::supervise();

    // TODO(T3): tray menu (Open dashboard / Pause detection / Restart
    // service / Quit), single instance, and window close-to-tray.
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running CamBrain shell");

    engine::mark_shutdown();
    engine::kill_child();
}
