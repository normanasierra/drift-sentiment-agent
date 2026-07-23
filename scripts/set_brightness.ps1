param([Parameter(Mandatory = $true)][int]$Percent)
# Set the external monitor's brightness to $Percent (0-100) of its DDC/CI range.
# Backs the desktop "Brillo NN%" shortcuts (launched windowless via brightness.vbs)
# and uses the same DDC/CI path as the WakandaBrightness scheduled tasks.
if ($Percent -lt 0)  { $Percent = 0 }
if ($Percent -gt 100) { $Percent = 100 }

$code = @"
using System;
using System.Runtime.InteropServices;
public class MonB {
  [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint f);
  [DllImport("dxva2.dll")] public static extern bool GetNumberOfPhysicalMonitorsFromHMONITOR(IntPtr h, ref uint n);
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct PM { public IntPtr h; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string d; }
  [DllImport("dxva2.dll")] public static extern bool GetPhysicalMonitorsFromHMONITOR(IntPtr h, uint n, [Out] PM[] a);
  [DllImport("dxva2.dll")] public static extern bool GetMonitorBrightness(IntPtr h, ref uint mn, ref uint cur, ref uint mx);
  [DllImport("dxva2.dll")] public static extern bool SetMonitorBrightness(IntPtr h, uint v);
  [DllImport("dxva2.dll")] public static extern bool DestroyPhysicalMonitors(uint n, [In] PM[] a);
}
"@
try {
  Add-Type -TypeDefinition $code -ErrorAction Stop
  $hmon = [MonB]::MonitorFromWindow([IntPtr]::Zero, 1)   # primary monitor
  $n = 0
  [void][MonB]::GetNumberOfPhysicalMonitorsFromHMONITOR($hmon, [ref]$n)
  if ($n -lt 1) { "no hay monitores físicos (DDC/CI)"; exit 1 }
  $arr = New-Object MonB+PM[] $n
  [void][MonB]::GetPhysicalMonitorsFromHMONITOR($hmon, $n, $arr)
  foreach ($m in $arr) {
    $mn = 0; $cur = 0; $mx = 0
    if ([MonB]::GetMonitorBrightness($m.h, [ref]$mn, [ref]$cur, [ref]$mx)) {
      $val = [int][math]::Round($mn + ($mx - $mn) * $Percent / 100.0)
      [void][MonB]::SetMonitorBrightness($m.h, $val)
      "OK brillo -> ${Percent}% (valor $val, rango $mn-$mx)"
    }
  }
  [void][MonB]::DestroyPhysicalMonitors($n, $arr)
} catch {
  "ERROR: $($_.Exception.Message)"; exit 1
}
