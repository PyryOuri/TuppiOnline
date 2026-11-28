// A pthread can grow shared memory while the owning worker is inside WASM.
// Refresh its exported JS views before copying buffers in the browser adapter.
Module['refreshHeap'] = function() {
  if (HEAPU8.buffer !== wasmMemory.buffer) updateMemoryViews();
};
Module['sharedMemory'] = wasmMemory;
