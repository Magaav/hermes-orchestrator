const CRC_TABLE = new Uint32Array(256);
for (let index = 0; index < 256; index += 1) {
  let value = index;
  for (let bit = 0; bit < 8; bit += 1) value = (value & 1) ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  CRC_TABLE[index] = value >>> 0;
}

async function crc32(blob: Blob) {
  let crc = 0xffffffff;
  const reader = blob.stream().getReader();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const byte of value) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function record(size: number) {
  return new DataView(new ArrayBuffer(size));
}

function dosDateTime(date = new Date()) {
  return {
    time: (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2),
    date: ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate()
  };
}

export async function createZip(entries: Array<{ name: string; blob: Blob }>) {
  const encoder = new TextEncoder();
  const parts: BlobPart[] = [];
  const central: Array<ArrayBuffer> = [];
  let offset = 0;
  for (const entry of entries) {
    const encodedName = encoder.encode(entry.name);
    const name = new ArrayBuffer(encodedName.byteLength);
    new Uint8Array(name).set(encodedName);
    const nameLength = encodedName.byteLength;
    const checksum = await crc32(entry.blob);
    const stamp = dosDateTime();
    const local = record(30);
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);
    local.setUint16(6, 0x0800, true);
    local.setUint16(10, stamp.time, true);
    local.setUint16(12, stamp.date, true);
    local.setUint32(14, checksum, true);
    local.setUint32(18, entry.blob.size, true);
    local.setUint32(22, entry.blob.size, true);
    local.setUint16(26, nameLength, true);
    parts.push(local.buffer, name, entry.blob);

    const header = record(46);
    header.setUint32(0, 0x02014b50, true);
    header.setUint16(4, 20, true);
    header.setUint16(6, 20, true);
    header.setUint16(8, 0x0800, true);
    header.setUint16(12, stamp.time, true);
    header.setUint16(14, stamp.date, true);
    header.setUint32(16, checksum, true);
    header.setUint32(20, entry.blob.size, true);
    header.setUint32(24, entry.blob.size, true);
    header.setUint16(28, nameLength, true);
    header.setUint32(42, offset, true);
    central.push(header.buffer, name);
    offset += 30 + nameLength + entry.blob.size;
  }
  const centralSize = central.reduce((total, part) => total + part.byteLength, 0);
  const end = record(22);
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, entries.length, true);
  end.setUint16(10, entries.length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);
  return new Blob([...parts, ...central, end.buffer], { type: "application/zip" });
}

export function cleanedFilename(name: string, index: number) {
  const safe = String(name || `foto-${index + 1}.jpg`).replace(/[\\/:*?"<>|]+/g, "-");
  const dot = safe.lastIndexOf(".");
  const stem = dot > 0 ? safe.slice(0, dot) : safe;
  return `${String(index + 1).padStart(2, "0")}-${stem}-studio.avif`;
}

export function downloadZip(blob: Blob) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `visao-studio-${new Date().toISOString().slice(0, 10)}.zip`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
