' Double-click: start the dashboard service with NO window at all.
' wscript.exe is a GUI app -> no console window ever appears.
' Stop it later with scripts\stop-service.bat (that does NOT stop the shared browser).
Option Explicit
Dim sh, fso, web, root, py, script, rc, logPath, exec, url
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
web = fso.GetParentFolderName(WScript.ScriptFullName)          ' ...\ad_management\web
root = fso.GetParentFolderName(web)                            ' ...\ad_management
py = fso.BuildPath(root, ".venv\Scripts\python.exe")
script = fso.BuildPath(root, "automation\scripts\board_service.py")
rc = sh.Run("""" & py & """ -u """ & script & """ --start", 0, True)
If rc <> 0 Then
  logPath = sh.ExpandEnvironmentStrings("%TEMP%\board_service.log")
  MsgBox "Dashboard service did NOT start." & vbCrLf & vbCrLf & _
         "Details: " & logPath & vbCrLf & _
         "Run board_service.py --status to see whether the dashboard is already running.", 16, "Dashboard service"
Else
  Set exec = sh.Exec("""" & py & """ -u """ & script & """ --url")
  url = Trim(exec.StdOut.ReadAll)
  If exec.ExitCode = 0 And Len(url) > 0 Then
    sh.Run url, 1, False
  Else
    MsgBox "Dashboard started, but the actual URL could not be read.", 16, "Dashboard service"
  End If
End If
