Unicode true
Name "WASM Agent"
OutFile "${OUT_FILE}"
Icon "icon.ico"
RequestExecutionLevel user
SilentInstall normal
ShowInstDetails hide

!define APP_GUID "8e77a95c-1554-58fc-9852-11d4a9707428"

Section "Remove WASM Agent"
  SetShellVarContext current
  Delete "$SMPROGRAMS\WASM Agent.lnk"
  Delete "$DESKTOP\WASM Agent.lnk"
  Delete "$LOCALAPPDATA\WASM Agent Native\shortcut-report.txt"
  RMDir "$LOCALAPPDATA\WASM Agent Native"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_GUID}"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_GUID}"
SectionEnd
