function k(d, a, b) {
  Array.isArray(a)
    ? a.forEach(function (a) {
        return d.addEventListener(a, b, !1);
      })
    : d.addEventListener(a, b, !1);
}
function fetch(d, a) {
  void 0 === a && (a = "GET");
  return new Promise(function (b, e) {
    var c = new XMLHttpRequest();
    c.onload = function () {
      var a = c.status;
      200 <= a && 300 > a ? b(c.responseText) : e(a + ": " + c.responseText);
    };
    c.open(a, d);
    c.send();
  });
}
new ((function () {
  function d() {
    var a = this;
    this.filter = document.getElementById("_id-filter");
    this.close = document.getElementById("_id-close");
    this.results = document.getElementById("_id-results");
    this.page = 1;
    this.morePages = !0;
    this.currentSearch = "";
    this.currentPage = 1;
    this.async = null;
    k(this.close, "click", function () {
      a.filter.value = "";
      a.page = 1;
      a.morePages = !0;
      a.fetch("");
    });
    k(this.filter, "input", function () {
      a.resetAsync();
      a.page = 1;
      a.morePages = !0;
      a.fetch(a.filter.value);
    });
    k(this.results, "scroll", function () {
      var b = a.results.scrollTop + a.results.offsetHeight;
      a.page == a.currentPage &&
        b > a.results.scrollHeight - 40 &&
        a.nextPage();
    });
  }
  d.prototype.resetAsync = function () {
    this.async = null;
  };
  d.prototype.clearResults = function () {
    for (; this.results.firstChild; )
      this.results.removeChild(this.results.firstChild);
  };
  d.prototype.render = function (a, b, e) {
    void 0 === e && (e = "");
    b || this.clearResults();
    for (b = 0; b < a.length; b++) {
      var c = a[b];
      this.addResult(c.name, c.slug, c.avatar, e);
    }
    this.results.scrollHeight < this.results.offsetHeight + 40 &&
      this.nextPage();
  };
  d.prototype.addResult = function (a, b, e, c) {
    void 0 === c && (c = "");
    var d = document.createElement("a");
    d.href = b;
    b = document.createElement("div");
    b.className = "_cls-result";
    var h = document.createElement("div");
    h.className = "_cls-inlineAvatar";
    var f = document.createElement("img");
    f.src = e;
    f.width = 22;
    f.height = 22;
    h.appendChild(f);
    b.appendChild(h);
    if ("" == c)
      (c = document.createElement("span")),
        (c.textContent = a),
        b.appendChild(c);
    else
      for (e = c.toLowerCase(), h = a.toLowerCase(); ; )
        if (((f = h.indexOf(e)), -1 != f)) {
          var g = document.createElement("span");
          g.textContent = a.substring(0, f);
          b.appendChild(g);
          g = document.createElement("b");
          g.textContent = a.substr(f, c.length);
          a = a.substr(f + c.length);
          h = h.substr(f + c.length);
          b.appendChild(g);
        } else {
          g = document.createElement("span");
          g.textContent = a;
          b.appendChild(g);
          break;
        }
    d.appendChild(b);
    this.results.appendChild(d);
  };
  d.prototype.fetch = function (a, b) {
    var d = this;
    void 0 === b && (b = !1);
    b || (this.results.scrollTop = 0);
    var c = this.page;
    this.currentSearch = a;
    this.async = fetch("autocomplete?q=" + a + "&page=" + c).then(function (e) {
      e = JSON.parse(e);
      d.currentSearch == a &&
        d.page == c &&
        ((e = e.data),
        (d.currentPage = c),
        0 == e.length && (d.morePages = !1),
        d.render(e, b, a),
        (d.async = null));
    });
  };
  d.prototype.nextPage = function () {
    this.morePages && (this.page++, this.fetch(this.filter.value, !0));
  };
  return d;
})())();
//# sourceMappingURL=main.js.map
