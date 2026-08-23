"use strict";

const SCHEMA = "hermes.wasm_agent.windows_audio_stimulus.v2";

function powershellSingleQuoted(value) {
  return `'${String(value || "").replace(/'/g, "''")}'`;
}

function parseJson(value, fallback = {}) {
  try { return JSON.parse(String(value || "").trim()); }
  catch { return fallback; }
}

function createAudioStimulus({ execFileBounded, platform = process.platform, now = () => Date.now() } = {}) {
  if (typeof execFileBounded !== "function") throw new TypeError("execFileBounded is required");

  async function runPowerShell(script, timeoutMs) {
    return execFileBounded("powershell.exe", [
      "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script,
    ], { timeoutMs, maxBuffer: 64 * 1024 });
  }

  async function listVoices(payload = {}) {
    const timeoutMs = Math.max(1000, Math.min(Math.round(Number(payload.timeoutMs || payload.timeout_ms || 8000)), 15000));
    if (platform !== "win32") return { ok: false, schema: SCHEMA, operation: "play_audio_stimulus", error: "windows_native_shell_required", stimulusKind: "voice_inventory" };
    const script = [
      "Add-Type -AssemblyName System.Speech;",
      "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer;",
      "try {",
      "$voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { [ordered]@{ name=$_.VoiceInfo.Name; culture=$_.VoiceInfo.Culture.Name; gender=$_.VoiceInfo.Gender.ToString(); age=$_.VoiceInfo.Age.ToString() } });",
      "[ordered]@{ voices=$voices } | ConvertTo-Json -Compress -Depth 4",
      "} finally { $synth.Dispose() }",
    ].join(" ");
    const startedAt = now();
    const result = await runPowerShell(script, timeoutMs);
    const parsed = parseJson(result.stdout, {});
    return {
      ok: result.ok && Array.isArray(parsed.voices), schema: SCHEMA, operation: "play_audio_stimulus",
      source: "windows_speech_synthesizer", stimulusKind: "voice_inventory",
      voices: Array.isArray(parsed.voices) ? parsed.voices.slice(0, 32) : [], timeoutMs,
      elapsedMs: now() - startedAt, exitCode: result.exitCode, timedOut: result.timedOut,
      error: result.error || result.stderr || (Array.isArray(parsed.voices) ? "" : "voice_inventory_invalid"),
    };
  }

  async function playWakePhraseProbe(payload = {}) {
    const phrase = String(payload.phrase || payload.wakePhrase || payload.wake_phrase || "alexa").replace(/\s+/g, " ").trim().slice(0, 240) || "alexa";
    const voice = String(payload.voice || payload.voiceName || payload.voice_name || "").replace(/\s+/g, " ").trim().slice(0, 120);
    const gender = String(payload.gender || payload.voiceGender || payload.voice_gender || "").replace(/[^A-Za-z]/g, "").slice(0, 20);
    const culture = String(payload.culture || payload.voiceCulture || payload.voice_culture || "").replace(/[^A-Za-z0-9-]/g, "").slice(0, 24);
    const rate = Math.max(-5, Math.min(Math.round(Number(payload.rate ?? -1)), 5));
    const volume = Math.max(0, Math.min(Math.round(Number(payload.volume ?? 100)), 100));
    const timeoutMs = Math.max(1000, Math.min(Math.round(Number(payload.timeoutMs || payload.timeout_ms || 12000)), 20000));
    if (platform !== "win32") return { ok: false, schema: SCHEMA, operation: "play_wake_phrase_probe", error: "windows_native_shell_required", phrase };
    const script = [
      "Add-Type -AssemblyName System.Speech;",
      `$phrase = ${powershellSingleQuoted(phrase)};`, `$voiceQuery = ${powershellSingleQuoted(voice)};`,
      `$genderQuery = ${powershellSingleQuoted(gender)};`, `$cultureQuery = ${powershellSingleQuoted(culture)};`,
      "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer;",
      `$synth.Rate = ${rate};`, `$synth.Volume = ${volume};`,
      "try {",
      "$voices = @($synth.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo });",
      "$selected = $null;",
      "if ($voiceQuery) { $selected = $voices | Where-Object { $_.Name -eq $voiceQuery } | Select-Object -First 1; if (-not $selected) { throw 'voice_not_found' } }",
      "elseif ($genderQuery -or $cultureQuery) { $selected = $voices | Where-Object { (-not $genderQuery -or $_.Gender.ToString() -eq $genderQuery) -and (-not $cultureQuery -or $_.Culture.Name -like ($cultureQuery + '*')) } | Select-Object -First 1; if (-not $selected) { throw 'voice_profile_not_found' } }",
      "if ($selected) { $synth.SelectVoice($selected.Name) }",
      "$synth.Speak($phrase); $active = $synth.Voice;",
      "[ordered]@{ voice=$active.Name; culture=$active.Culture.Name; gender=$active.Gender.ToString() } | ConvertTo-Json -Compress",
      "} finally { $synth.Dispose() }",
    ].join(" ");
    const startedAt = now();
    const result = await runPowerShell(script, timeoutMs);
    const selected = parseJson(result.stdout, {});
    return {
      ok: result.ok, schema: SCHEMA, operation: "play_wake_phrase_probe", source: "windows_speech_synthesizer",
      phrase, rate, volume, requestedVoice: voice, requestedGender: gender, requestedCulture: culture,
      selectedVoice: String(selected.voice || ""), selectedGender: String(selected.gender || ""), selectedCulture: String(selected.culture || ""),
      timeoutMs, elapsedMs: now() - startedAt, exitCode: result.exitCode, timedOut: result.timedOut,
      error: result.error || result.stderr || "",
    };
  }

  async function playAudioStimulus(payload = {}) {
    const rawKind = String(payload.kind || payload.stimulus || payload.type || "speech").toLowerCase();
    const kind = ["speech", "voice_inventory", "system_sound", "beep", "silence"].includes(rawKind) ? rawKind : "speech";
    const label = String(payload.label || payload.stimulusId || payload.stimulus_id || kind).replace(/[^A-Za-z0-9_.:-]+/g, "_").slice(0, 80) || kind;
    const durationMs = Math.max(100, Math.min(Math.round(Number(payload.durationMs || payload.duration_ms || 700)), 5000));
    const timeoutMs = Math.max(1000, Math.min(Math.round(Number(payload.timeoutMs || payload.timeout_ms || durationMs + 5000)), 20000));
    if (kind === "voice_inventory") return { ...(await listVoices({ ...payload, timeoutMs })), stimulusLabel: label };
    if (kind === "speech") return { ...(await playWakePhraseProbe({ ...payload, phrase: payload.phrase || payload.text || payload.wakePhrase || payload.wake_phrase || "alexa", timeoutMs })), operation: "play_audio_stimulus", stimulusKind: kind, stimulusLabel: label, nestedOperation: "play_wake_phrase_probe" };
    if (platform !== "win32") return { ok: false, schema: SCHEMA, operation: "play_audio_stimulus", error: "windows_native_shell_required", stimulusKind: kind, stimulusLabel: label };
    let script = "";
    if (kind === "silence") script = `Start-Sleep -Milliseconds ${durationMs};`;
    else if (kind === "system_sound") {
      const sound = String(payload.sound || payload.systemSound || payload.system_sound || "Exclamation").replace(/[^A-Za-z]/g, "");
      const safeSound = ["Asterisk", "Beep", "Exclamation", "Hand", "Question"].includes(sound) ? sound : "Exclamation";
      script = `Add-Type -AssemblyName System.Windows.Forms; [System.Media.SystemSounds]::${safeSound}.Play(); Start-Sleep -Milliseconds ${durationMs};`;
    } else {
      const frequencyHz = Math.max(120, Math.min(Math.round(Number(payload.frequencyHz || payload.frequency_hz || payload.frequency || 880)), 4000));
      script = `[Console]::Beep(${frequencyHz}, ${durationMs});`;
    }
    const startedAt = now();
    const result = await runPowerShell(script, timeoutMs);
    return { ok: result.ok, schema: SCHEMA, operation: "play_audio_stimulus", source: "windows_fixed_audio_stimulus", stimulusKind: kind, stimulusLabel: label, durationMs, timeoutMs, elapsedMs: now() - startedAt, exitCode: result.exitCode, timedOut: result.timedOut, error: result.error || result.stderr || "" };
  }

  return { listVoices, playWakePhraseProbe, playAudioStimulus };
}

module.exports = { SCHEMA, createAudioStimulus, powershellSingleQuoted };
