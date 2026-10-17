; CamBrain NSIS installer hooks (Tauri v2 bundler supports these macros).
; D6-8: per-user install under %LOCALAPPDATA%\Programs\CamBrain — NOT the
; Tauri default (%LOCALAPPDATA%\CamBrain), because D6-3 reserves that
; directory for APP DATA (DB, media, keys): an uninstall must never be able
; to delete user data. The silent flow (/S, Arun's documented path) installs
; after PREINSTALL, so the override holds there.
; D6-2: autostart on user session is a HKCU Run key set by the installer —
; not a Windows service (the engine is a supervised child, and a service
; can't own a per-user tray + window). Uninstall removes the key.

!macro NSIS_HOOK_PREINSTALL
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\CamBrain"
  ; NSIS File copies target $OUTDIR (set before this hook), so the
  ; redirected $INSTDIR must be re-set as the output path first.
  SetOutPath "$INSTDIR"
!macroend

!macro NSIS_HOOK_POSTINSTALL
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "CamBrain" "$INSTDIR\CamBrain.exe"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "CamBrain"
!macroend
