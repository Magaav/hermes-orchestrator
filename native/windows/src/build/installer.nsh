!macro customInstall
  CreateDirectory "$LOCALAPPDATA\WASM Agent Native"
  ${If} ${FileExists} "$INSTDIR\resources\wasm-agent-launcher.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "WASM Agent" '"$INSTDIR\resources\wasm-agent-launcher.exe"'
    ${If} ${FileExists} "$INSTDIR\resources\icon.ico"
      ${If} $installMode == "all"
        SetShellVarContext current
        Delete "$SMPROGRAMS\WASM Agent.lnk"
        Delete "$DESKTOP\WASM Agent.lnk"
        SetShellVarContext all
      ${Else}
        SetShellVarContext current
      ${EndIf}
      Delete "$SMPROGRAMS\WASM Agent.lnk"
      Delete "$DESKTOP\WASM Agent.lnk"
      CreateShortCut "$SMPROGRAMS\WASM Agent.lnk" "$INSTDIR\resources\wasm-agent-launcher.exe" "" "$INSTDIR\resources\icon.ico" 0
      CreateShortCut "$DESKTOP\WASM Agent.lnk" "$INSTDIR\resources\wasm-agent-launcher.exe" "" "$INSTDIR\resources\icon.ico" 0
    ${EndIf}
  ${EndIf}
  ClearErrors
  FileOpen $0 "$LOCALAPPDATA\WASM Agent Native\shortcut-report.txt" w
  IfErrors wasm_agent_shortcut_report_done
  FileWrite $0 "ok | electron-builder NSIS install path | $INSTDIR$\r$\n"
  FileWrite $0 "ok | supervisor launcher | $INSTDIR\resources\wasm-agent-launcher.exe$\r$\n"
  FileWrite $0 "ok | shortcut icon | $INSTDIR\resources\icon.ico$\r$\n"
  FileWrite $0 "ok | desktop shortcut policy | createDesktopShortcut=always$\r$\n"
  FileWrite $0 "ok | start menu shortcut policy | createStartMenuShortcut=true$\r$\n"
  FileWrite $0 "ok | authoritative shortcut scope | $installMode; stale current-user shortcuts removed by all-users install$\r$\n"
  FileClose $0
wasm_agent_shortcut_report_done:
!macroend

!macro customUnInstall
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "WASM Agent"
  Delete "$LOCALAPPDATA\WASM Agent Native\shortcut-report.txt"
  RMDir "$LOCALAPPDATA\WASM Agent Native"
!macroend
