"use strict";

const { execFile } = require("node:child_process");

const SCHEMA = "hermes.wasm_agent.windows_audio_signal_probe.v1";
const OPERATION = "probe_windows_audio_signal";
const MAX_OUTPUT_BYTES = 64 * 1024;

function text(value, maxLength = 240) {
  return String(value || "").replace(/\s+/g, " ").trim().slice(0, maxLength);
}

function psQuote(value) {
  return `'${String(value || "").replace(/'/g, "''")}'`;
}

function powershellSignalScript({ phrase, voice, captureMs }) {
  return [
    "$ErrorActionPreference = 'Stop';",
    "Add-Type -AssemblyName System.Speech;",
    "$native = @'",
    "using System; using System.Runtime.InteropServices;",
    "public static class WaveSignalProbe {",
    "[StructLayout(LayoutKind.Sequential)] public struct WAVEFORMATEX { public ushort wFormatTag,nChannels; public uint nSamplesPerSec,nAvgBytesPerSec; public ushort nBlockAlign,wBitsPerSample,cbSize; }",
    "[StructLayout(LayoutKind.Sequential)] public struct WAVEHDR { public IntPtr lpData; public uint dwBufferLength,dwBytesRecorded; public IntPtr dwUser; public uint dwFlags,dwLoops; public IntPtr lpNext,reserved; }",
    "[DllImport(\"winmm.dll\")] static extern int waveInOpen(out IntPtr h,uint id,ref WAVEFORMATEX f,IntPtr cb,IntPtr i,uint flags);",
    "[DllImport(\"winmm.dll\")] static extern int waveInPrepareHeader(IntPtr h,IntPtr p,uint n); [DllImport(\"winmm.dll\")] static extern int waveInAddBuffer(IntPtr h,IntPtr p,uint n);",
    "[DllImport(\"winmm.dll\")] static extern int waveInStart(IntPtr h); [DllImport(\"winmm.dll\")] static extern int waveInStop(IntPtr h); [DllImport(\"winmm.dll\")] static extern int waveInReset(IntPtr h);",
    "[DllImport(\"winmm.dll\")] static extern int waveInUnprepareHeader(IntPtr h,IntPtr p,uint n); [DllImport(\"winmm.dll\")] static extern int waveInClose(IntPtr h);",
    "public static double[] Capture(Action play,int ms) { IntPtr h=IntPtr.Zero,data=IntPtr.Zero,hdrp=IntPtr.Zero; var f=new WAVEFORMATEX{wFormatTag=1,nChannels=1,nSamplesPerSec=16000,nAvgBytesPerSec=32000,nBlockAlign=2,wBitsPerSample=16}; int bytes=Math.Max(3200,ms*32); try { int rc=waveInOpen(out h,0xFFFFFFFF,ref f,IntPtr.Zero,IntPtr.Zero,0); if(rc!=0) throw new Exception(\"waveInOpen:\"+rc); data=Marshal.AllocHGlobal(bytes); for(int i=0;i<bytes;i++) Marshal.WriteByte(data,i,0); var hdr=new WAVEHDR{lpData=data,dwBufferLength=(uint)bytes}; int hs=Marshal.SizeOf(typeof(WAVEHDR)); hdrp=Marshal.AllocHGlobal(hs); Marshal.StructureToPtr(hdr,hdrp,false); if((rc=waveInPrepareHeader(h,hdrp,(uint)hs))!=0||(rc=waveInAddBuffer(h,hdrp,(uint)hs))!=0||(rc=waveInStart(h))!=0) throw new Exception(\"waveInStart:\"+rc); play(); System.Threading.Thread.Sleep(350); waveInStop(h); waveInReset(h); hdr=(WAVEHDR)Marshal.PtrToStructure(hdrp,typeof(WAVEHDR)); int count=(int)hdr.dwBytesRecorded/2; double sum=0,peak=0; for(int i=0;i<count;i++){short s=Marshal.ReadInt16(data,i*2);double a=Math.Abs((double)s)/32768.0;if(a>peak)peak=a;sum+=a*a;} return new[]{peak,count>0?Math.Sqrt(sum/count):0,count/16000.0}; } finally { if(h!=IntPtr.Zero){if(hdrp!=IntPtr.Zero)waveInUnprepareHeader(h,hdrp,(uint)Marshal.SizeOf(typeof(WAVEHDR)));waveInClose(h);}if(hdrp!=IntPtr.Zero)Marshal.FreeHGlobal(hdrp);if(data!=IntPtr.Zero)Marshal.FreeHGlobal(data);} }",
    "}",
    "'@; Add-Type -TypeDefinition $native -Language CSharp;",
    `$phrase=${psQuote(phrase)}; $voice=${psQuote(voice)}; $captureMs=${captureMs};`,
    "$synth=New-Object System.Speech.Synthesis.SpeechSynthesizer; try { if($voice){$synth.SelectVoice($voice)}; $metrics=[WaveSignalProbe]::Capture({$synth.Speak($phrase)},$captureMs); $active=$synth.Voice; [ordered]@{peak=[math]::Round($metrics[0],6);rms=[math]::Round($metrics[1],6);capturedSeconds=[math]::Round($metrics[2],3);voice=$active.Name;culture=$active.Culture.Name;gender=$active.Gender.ToString()}|ConvertTo-Json -Compress } finally {$synth.Dispose()}",
  ].join("\n");
}

function classifySignal(raw = {}) {
  const peak = Number(raw.peak || 0);
  const rms = Number(raw.rms || 0);
  const signalPresent = peak >= 0.01 && rms >= 0.001;
  return { signalPresent, failureClassification: signalPresent ? "pass" : "audio_loopback_silent", peak, rms };
}

async function run(context = {}, dependencies = {}) {
  if ((dependencies.platform || process.platform) !== "win32") return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "windows_native_shell_required" };
  const phrase = text(context.args?.phrase || "Audio signal probe confirms the virtual cable path.", 240);
  const voice = text(context.args?.voice || "Microsoft David Desktop", 120);
  const captureMs = Math.max(2000, Math.min(Number(context.args?.captureMs || 8000), 12000));
  const execute = dependencies.execute || ((script) => new Promise((resolve) => execFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script], { timeout: captureMs + 8000, maxBuffer: MAX_OUTPUT_BYTES, windowsHide: true, encoding: "utf8" }, (error, stdout, stderr) => resolve({ ok: !error, stdout, stderr, error }))));
  context.markPhase?.("audio_signal_probe_started");
  const command = await execute(powershellSignalScript({ phrase, voice, captureMs }));
  if (!command.ok) return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "audio_signal_probe_failed", error: text(command.stderr || command.error?.message, 1000) };
  let raw; try { raw = JSON.parse(String(command.stdout || "").trim()); } catch { return { schema: SCHEMA, operation: OPERATION, ok: false, failureClassification: "audio_signal_probe_invalid" }; }
  const signal = classifySignal(raw);
  context.markPhase?.("audio_signal_probe_complete", signal);
  return { schema: SCHEMA, operation: OPERATION, ok: signal.signalPresent, stable: signal.signalPresent, ...signal, phrase, requestedVoice: voice, selectedVoice: text(raw.voice, 120), selectedCulture: text(raw.culture, 24), selectedGender: text(raw.gender, 20), capturedSeconds: Number(raw.capturedSeconds || 0), nextAction: signal.signalPresent ? "Run the Realure Anamnese transcription fixture." : "Inspect or pin the Windows render path feeding VB-CABLE before testing transcription." };
}

module.exports = { OPERATION, SCHEMA, classifySignal, powershellSignalScript, run };
