// Prevent an extra console window on Windows release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::menu::{CheckMenuItem, Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, WindowEvent};

mod engine;
mod instance;

fn focus_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn main() {
    // D6-7: two shells never run at once — the second raises the first's
    // window and exits.
    if let instance::Instance::Secondary(hwnd) = instance::acquire() {
        instance::focus_running(hwnd);
        return;
    }

    tauri::Builder::default()
        .setup(|app| {
            // D6-6: the tray menu is normative (design.md §tray). "Pause
            // detection" is the installer's panic button; in the MVP it holds
            // the engine down (degraded form, documented in DEPLOYMENT) —
            // the HTTP toggle needs a credential handoff that is post-MVP.
            let open = MenuItem::with_id(app, "open", "Open dashboard", true, None::<&str>)?;
            let pause =
                CheckMenuItem::with_id(app, "pause", "Pause detection", true, false, None::<&str>)?;
            let restart = MenuItem::with_id(app, "restart", "Restart service", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &pause, &restart, &quit])?;

            let pause_handle = pause.clone();
            TrayIconBuilder::with_id("cambrian-tray")
                .icon(app.default_window_icon().expect("bundled icon").clone())
                .tooltip("CamBrain")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(move |app, event| match event.id().0.as_str() {
                    "open" => focus_main(app),
                    "pause" => {
                        // The native checkbox flips before the event lands;
                        // its checked state IS the requested pause state.
                        let checked = pause_handle.is_checked().unwrap_or(false);
                        engine::set_paused(checked);
                        if checked {
                            engine::kill_child(); // hold the engine down now
                        }
                        // Unchecking: the supervisor respawns within a second.
                    }
                    "restart" => engine::kill_child(),
                    "quit" => {
                        engine::mark_shutdown();
                        engine::kill_child();
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            let window = app.get_webview_window("main").expect("main window");
            let hidden = window.clone();
            window.on_window_event(move |event| {
                // D6-5: closing the window hides it to tray; the engine and
                // tray stay up. Quit lives only in the tray menu.
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = hidden.hide();
                }
            });

            engine::supervise();
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running CamBrain shell");

    engine::mark_shutdown();
    engine::kill_child();
}
