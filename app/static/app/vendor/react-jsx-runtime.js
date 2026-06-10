/* react/jsx-runtime (React 18.3.1) wrapped as a UMD global `jsxRuntime`.
 * The @xyflow/react UMD build imports `react/jsx-runtime`; React ships no
 * UMD build for it, so we load the real CJS module against window.React.
 * Source: react@18.3.1 cjs/react-jsx-runtime.production.min.js (verbatim). */
;(function (global) {
  var module = { exports: {} };
  function require(name) {
    if (name === "react") return global.React;
    throw new Error("jsx-runtime shim: unexpected require(" + name + ")");
  }
  (function (module, exports, require) {
/**
 * @license React
 * react-jsx-runtime.production.min.js
 *
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */
'use strict';var f=require("react"),k=Symbol.for("react.element"),l=Symbol.for("react.fragment"),m=Object.prototype.hasOwnProperty,n=f.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentOwner,p={key:!0,ref:!0,__self:!0,__source:!0};
function q(c,a,g){var b,d={},e=null,h=null;void 0!==g&&(e=""+g);void 0!==a.key&&(e=""+a.key);void 0!==a.ref&&(h=a.ref);for(b in a)m.call(a,b)&&!p.hasOwnProperty(b)&&(d[b]=a[b]);if(c&&c.defaultProps)for(b in a=c.defaultProps,a)void 0===d[b]&&(d[b]=a[b]);return{$$typeof:k,type:c,key:e,ref:h,props:d,_owner:n.current}}exports.Fragment=l;exports.jsx=q;exports.jsxs=q;

  })(module, module.exports, require);
  global.jsxRuntime = module.exports;
})(typeof globalThis !== "undefined" ? globalThis : this);
