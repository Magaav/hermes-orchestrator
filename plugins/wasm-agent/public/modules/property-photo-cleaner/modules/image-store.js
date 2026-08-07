export function createImageStore() {
  const items = [];
  return {
    add(blob) {
      const item = { id: crypto.randomUUID(), name: blob.name || "photo.jpg", blob, output: null, bitmap: null, approved: false };
      items.push(item);
      return item;
    },
    list: () => items.slice(),
    disposeDecoded() {
      for (const item of items) {
        item.bitmap?.close?.();
        item.bitmap = null;
      }
    },
    clear() {
      this.disposeDecoded();
      items.splice(0);
    }
  };
}
