!macro customInstall
  CreateDirectory "$LOCALAPPDATA\WASM Agent Native"
  ClearErrors
  FileOpen $0 "$LOCALAPPDATA\WASM Agent Native\shortcut-report.txt" w
  IfErrors wasm_agent_shortcut_report_done
  FileWrite $0 "ok | electron-builder NSIS install path | $INSTDIR$\r$\n"
  FileWrite $0 "ok | desktop shortcut policy | createDesktopShortcut=always$\r$\n"
  FileWrite $0 "ok | start menu shortcut policy | createStartMenuShortcut=true$\r$\n"
  FileClose $0
wasm_agent_shortcut_report_done:
!macroend

!macro customUnInstall
  Delete "$LOCALAPPDATA\WASM Agent Native\shortcut-report.txt"
  RMDir "$LOCALAPPDATA\WASM Agent Native"
!macroend
