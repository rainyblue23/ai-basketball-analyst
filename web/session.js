(function () {
  'use strict';
  if (location.protocol === 'file:') return;
  var originalFetch = window.fetch.bind(window), redirecting = false;
  window.fetch = function (input, options) {
    return originalFetch(input, options).then(function (response) {
      var url = new URL(typeof input === 'string' ? input : input.url, location.href);
      if (response.status === 401 && url.origin === location.origin && url.pathname.startsWith('/api/') && url.pathname !== '/api/login') {
        if (!redirecting) {
          redirecting = true;
          location.replace('/web/login.html?next=' + encodeURIComponent(location.pathname + location.search + location.hash));
        }
        // Do not turn authentication failure into offline demo data while navigation is pending.
        return new Promise(function () {});
      }
      return response;
    });
  };
  window.AIHOOP_LOGOUT = async function () {
    var button = document.getElementById('logout-button');
    if (button) button.disabled = true;
    try {
      var response = await originalFetch('/api/logout', {method:'POST'});
      if (!response.ok && response.status !== 401) throw new Error('logout');
      location.replace('/web/login.html');
    } catch (_) {
      alert('退出未完成，请检查连接后重试。');
      if (button) button.disabled = false;
    }
  };
})();
