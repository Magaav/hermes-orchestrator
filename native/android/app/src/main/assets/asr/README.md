# Android Local ASR Assets

Place the bundled Vosk command model directory here as:

```text
assets/asr/vosk-model/
```

On voice wake service start, Android copies that directory to app-private
storage at:

```text
files/asr/vosk-model/
```

The local command recognizer uses a small grammar for post-Hermes commands such
as `open wake word`, `start listener`, and `stop listener`. If the asset is not
packaged, diagnostics must report `local_asr_vosk_ready: false` and
`local_asr_vosk_asset_available: false`; `transcriptEngine=auto` falls back to
Android SpeechRecognizer, while `transcriptEngine=vosk` reports
`vosk_model_missing`.
