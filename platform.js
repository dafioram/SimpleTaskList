/* SimpleTaskList — platform layer.
 *
 * The only file that asks whether we're in the Android app (Capacitor) or in a
 * browser. store.js and app.js call these helpers instead of checking themselves.
 *
 *   Platform.isNative           true inside the Android app
 *   Platform.callNative(...)    call a Capacitor plugin; returns a promise
 *   Platform.shareTextFile(...) hand a text file to the Android share sheet
 */
(function () {
  'use strict';

  var isNative = !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());

  function callNative(plugin, method, options) {
    return window.Capacitor.nativePromise(plugin, method, options || {});
  }

  /** Saves text to the app's cache and opens the share sheet (Files, Drive, email...). */
  function shareTextFile(text, name) {
    return callNative('Filesystem', 'writeFile', { path: name, data: text, directory: 'CACHE', encoding: 'utf8' })
      .then(function (res) {
        return callNative('Share', 'share', { title: name, dialogTitle: 'Save backup', files: [res.uri] });
      });
  }

  window.Platform = {
    isNative: isNative,
    callNative: callNative,
    shareTextFile: shareTextFile
  };
})();
