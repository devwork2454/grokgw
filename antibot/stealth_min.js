// stealth_min.js - 精简加固脚本,只做最关键且不破坏页面的修补
// DrissionPage CDP 直连:webdriver 默认 false,plugins/languages 正常,
// 主要破绽是 UA 含 HeadlessChrome。这里只修 UA,其余交给启动参数。

(function () {
    'use strict';
    try {
        var ua = navigator.userAgent;
        if (ua.indexOf('HeadlessChrome') > -1) {
            var fixed = ua.replace(/HeadlessChrome/g, 'Chrome');
            Object.defineProperty(Navigator.prototype, 'userAgent', {
                get: function () { return fixed; }, configurable: true
            });
            var av = navigator.appVersion;
            if (av && av.indexOf('HeadlessChrome') > -1) {
                var fixedAv = av.replace(/HeadlessChrome/g, 'Chrome');
                Object.defineProperty(Navigator.prototype, 'appVersion', {
                    get: function () { return fixedAv; }, configurable: true
                });
            }
        }
    } catch (e) {}
    // 防御性清除 webdriver(虽默认已是 false)
    try {
        Object.defineProperty(Navigator.prototype, 'webdriver', {
            get: function () { return false; }, configurable: true
        });
    } catch (e) {}
})();
