use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::f64::consts::PI;
use wasm_bindgen::prelude::*;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct LogEvent {
    id: String,
    channel: String,
    ts: String,
    severity: String,
    message: String,
}

#[derive(Debug, Clone, Serialize)]
struct HeatBucket {
    hour: usize,
    count: u32,
    warning: u32,
    error: u32,
}

#[wasm_bindgen]
pub fn normalize_lines(lines: &str, channel: &str) -> String {
    let normalized: Vec<LogEvent> = lines
        .lines()
        .enumerate()
        .map(|(idx, line)| LogEvent {
            id: format!("wasm-{idx}"),
            channel: channel.to_string(),
            ts: parse_timestamp(line),
            severity: infer_severity(line).to_string(),
            message: line.to_string(),
        })
        .collect();

    serde_json::to_string(&normalized).unwrap_or_else(|_| "[]".to_string())
}

#[wasm_bindgen]
pub fn aggregate_heatmap(events_json: &str) -> String {
    let events: Vec<LogEvent> = serde_json::from_str(events_json).unwrap_or_default();
    let mut buckets = (0..24)
        .map(|hour| HeatBucket {
            hour,
            count: 0,
            warning: 0,
            error: 0,
        })
        .collect::<Vec<_>>();

    for event in events {
        let hour = extract_hour(&event.ts).unwrap_or(0).min(23);
        let bucket = &mut buckets[hour];
        bucket.count += 1;

        match event.severity.as_str() {
            "warning" => bucket.warning += 1,
            "error" => bucket.error += 1,
            _ => {}
        }
    }

    serde_json::to_string(&buckets).unwrap_or_else(|_| "[]".to_string())
}

#[wasm_bindgen]
pub fn layout_graph(nodes_json: &str, edges_json: &str) -> String {
    let mut nodes: Vec<Value> = serde_json::from_str(nodes_json).unwrap_or_default();
    let edges: Vec<Value> = serde_json::from_str(edges_json).unwrap_or_default();

    let radius = 180.0_f64;
    let center_x = 220.0_f64;
    let center_y = 220.0_f64;
    let n = nodes.len().max(1) as f64;

    for (idx, node) in nodes.iter_mut().enumerate() {
        let angle = 2.0 * PI * idx as f64 / n;
        let x = center_x + radius * angle.cos();
        let y = center_y + radius * angle.sin();

        if let Some(obj) = node.as_object_mut() {
            obj.insert("x".to_string(), json!(x));
            obj.insert("y".to_string(), json!(y));
        }
    }

    serde_json::to_string(&json!({
        "nodes": nodes,
        "edges": edges,
    }))
    .unwrap_or_else(|_| "{}".to_string())
}

fn infer_severity(line: &str) -> &'static str {
    let lower = line.to_ascii_lowercase();
    if contains_any(
        &lower,
        &["error", "fatal", "panic", "critical", "traceback", "exception"],
    ) {
        return "error";
    }
    if contains_any(&lower, &["warn", "warning", "forbidden", "denied", "429"]) {
        return "warning";
    }
    "info"
}

fn contains_any(haystack: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| haystack.contains(needle))
}

fn parse_timestamp(line: &str) -> String {
    let trimmed = line.trim();

    let candidate = if let Some(stripped) = trimmed.strip_prefix('[') {
        stripped.split(']').next().unwrap_or(trimmed)
    } else {
        trimmed.split_whitespace().next().unwrap_or(trimmed)
    };

    normalize_iso_like(candidate).unwrap_or_else(|| "1970-01-01T00:00:00Z".to_string())
}

fn normalize_iso_like(value: &str) -> Option<String> {
    if value.len() < 19 {
        return None;
    }

    let mut cleaned = value.replace(' ', "T");
    if cleaned.ends_with('Z') {
        return Some(cleaned);
    }

    // If explicit offset exists, leave as-is.
    if cleaned
        .get(19..)
        .map(|tail| tail.starts_with('+') || tail.starts_with('-'))
        .unwrap_or(false)
    {
        return Some(cleaned);
    }

    cleaned.push('Z');
    Some(cleaned)
}

fn extract_hour(ts: &str) -> Option<usize> {
    let t_pos = ts.find('T')?;
    let hour_start = t_pos + 1;
    let hour_end = hour_start + 2;
    let hour_text = ts.get(hour_start..hour_end)?;
    hour_text.parse::<usize>().ok()
}
