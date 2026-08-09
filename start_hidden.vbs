Option Explicit

Dim shell
Dim fso
Dim root
Dim managerPath
Dim pythonwPath
Dim command
Dim args
Dim i

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
managerPath = root & "\scripts\manage.py"
pythonwPath = root & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonwPath) Then
  MsgBox "Project Python was not found: " & pythonwPath, vbCritical, "Start failed"
  WScript.Quit 1
End If

If Not fso.FileExists(managerPath) Then
  MsgBox "Process manager was not found: " & managerPath, vbCritical, "Start failed"
  WScript.Quit 1
End If

args = ""
For i = 0 To WScript.Arguments.Count - 1
  args = args & " " & Quote(WScript.Arguments(i))
Next

command = Quote(pythonwPath) & " " & Quote(managerPath) & " start" & args
shell.CurrentDirectory = root
shell.Run command, 0, False

Function Quote(value)
  Quote = Chr(34) & Replace(CStr(value), Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
