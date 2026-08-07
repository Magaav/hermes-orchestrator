const encoder = new TextEncoder();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function header(size) {
  return new DataView(new ArrayBuffer(size));
}

function bytes(view) {
  return new Uint8Array(view.buffer);
}

export function buildStoreZip(entries) {
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  for (const [path, value] of Object.entries(entries)) {
    const name = encoder.encode(path);
    const data = typeof value === "string" ? encoder.encode(value) : new Uint8Array(value);
    const checksum = crc32(data);
    const local = header(30);
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);
    local.setUint16(6, 0x0800, true);
    local.setUint32(14, checksum, true);
    local.setUint32(18, data.byteLength, true);
    local.setUint32(22, data.byteLength, true);
    local.setUint16(26, name.byteLength, true);
    localParts.push(bytes(local), name, data);

    const central = header(46);
    central.setUint32(0, 0x02014b50, true);
    central.setUint16(4, 20, true);
    central.setUint16(6, 20, true);
    central.setUint16(8, 0x0800, true);
    central.setUint32(16, checksum, true);
    central.setUint32(20, data.byteLength, true);
    central.setUint32(24, data.byteLength, true);
    central.setUint16(28, name.byteLength, true);
    central.setUint32(42, offset, true);
    centralParts.push(bytes(central), name);
    offset += 30 + name.byteLength + data.byteLength;
  }
  const centralSize = centralParts.reduce((total, part) => total + part.byteLength, 0);
  const end = header(22);
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, Object.keys(entries).length, true);
  end.setUint16(10, Object.keys(entries).length, true);
  end.setUint32(12, centralSize, true);
  end.setUint32(16, offset, true);
  return new Blob([...localParts, ...centralParts, bytes(end)], { type: "application/zip" });
}
