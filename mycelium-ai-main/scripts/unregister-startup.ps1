# Removes the user-level logon task. Data (databases, memories)
# is untouched — only autostart is disabled.
Unregister-ScheduledTask -TaskName "MyceliumCoordinator" -Confirm:$false
Write-Output "Mycelium autostart disabled."
