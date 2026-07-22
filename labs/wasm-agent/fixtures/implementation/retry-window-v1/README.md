# Retry Window

`RetryWindow` admits at most `limit` events during the preceding
`window_seconds`. An event at exactly `now - window_seconds` is expired.

Run the focused check with:

```bash
python3 -m unittest discover -s tests -v
```
