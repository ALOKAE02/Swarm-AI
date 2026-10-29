// Simulated ad network: noisy, broken, and not your app's fault.
console.error('[adnet] bid request failed: 503 Service Unavailable');
setTimeout(function adnetRefresh() {
  var slot;
  slot.refresh();  // throws from a third-party origin
}, 600);
