function d(id) {
  return document.getElementById(id);
}
// Set event listener
function on(element, event, fn) {
  if (Array.isArray(event)) {
    event.forEach(function(evt) {
      return element.addEventListener(evt, fn, false);
    });
  } else {
    element.addEventListener(event, fn, false);
  }
}

var SCROLL_BUFFER = 40;
var View = /** @class */ (function() {
  function View() {
    var _this = this;
    this.filter = d('_id-filter');
    this.close = d('_id-close');
    this.results = d('_id-results');
    this.page = 1;
    this.morePages = true;
    this.currentSearch = '';
    this.currentPage = 1;
    this.async = null;
    on(this.close, 'click', function() {
      _this.filter.value = '';
      _this.page = 1;
      _this.morePages = true;
      _this.fetch('');
    });
    on(this.filter, 'input', function() {
      _this.resetAsync();
      _this.page = 1;
      _this.morePages = true;
      _this.fetch(_this.filter.value);
    });
    on(this.results, 'scroll', function() {
      var position = _this.results.scrollTop + _this.results.offsetHeight;
      if (
        _this.page == _this.currentPage &&
        position > _this.results.scrollHeight - SCROLL_BUFFER
      ) {
        _this.nextPage();
      }
    });
  }
  View.prototype.resetAsync = function() {
    this.async = null;
  };
  View.prototype.clearResults = function() {
    while (this.results.firstChild) this.results.removeChild(this.results.firstChild);
  };
  View.prototype.render = function(json, append, term) {
    if (term === void 0) {
      term = '';
    }
    if (!append) {
      this.clearResults();
    }
    for (var _i = 0, json_1 = json; _i < json_1.length; _i++) {
      var result = json_1[_i];
      this.addResult(result.name, result.slug, result.avatar, term);
    }
    if (this.results.scrollHeight < this.results.offsetHeight + SCROLL_BUFFER) {
      this.nextPage();
    }
  };
  View.prototype.addResult = function(text, link, avatarUrl, highlight) {
    if (highlight === void 0) {
      highlight = '';
    }
    var a = document.createElement('a');
    a.href = link;
    var div = document.createElement('div');
    div.className = '_cls-result';
    var avatar = document.createElement('div');
    avatar.className = '_cls-inlineAvatar';
    var avatarImg = document.createElement('img');
    avatarImg.src = avatarUrl;
    avatarImg.width = 22;
    avatarImg.height = 22;
    avatar.appendChild(avatarImg);
    div.appendChild(avatar);
    if (highlight == '') {
      var span = document.createElement('span');
      span.textContent = text;
      div.appendChild(span);
    } else {
      var lowerHighlight = highlight.toLowerCase();
      var lowerText = text.toLowerCase();
      while (true) {
        var i = lowerText.indexOf(lowerHighlight);
        if (i != -1) {
          var normal = document.createElement('span');
          normal.textContent = text.substring(0, i);
          div.appendChild(normal);
          var bold = document.createElement('b');
          bold.textContent = text.substr(i, highlight.length);
          text = text.substr(i + highlight.length);
          lowerText = lowerText.substr(i + highlight.length);
          div.appendChild(bold);
        } else {
          var normal = document.createElement('span');
          normal.textContent = text;
          div.appendChild(normal);
          break;
        }
      }
    }
    a.appendChild(div);
    this.results.appendChild(a);
  };
  View.prototype.fetch = function(term, append) {
    var _this = this;
    if (append === void 0) {
      append = false;
    }
    if (!append) {
      // Scroll back to the top on new query
      this.results.scrollTop = 0;
    }
    var page = this.page;
    this.currentSearch = term;
    this.async = fetch('autocomplete?q=' + term + '&page=' + page)
      .then(function(response) {
        return response.json();
      })
      .then(function(myJson) {
        if (_this.currentSearch == term && _this.page == page) {
          var results = myJson.data;
          _this.currentPage = page;
          if (results.length == 0) {
            _this.morePages = false;
          }
          _this.render(results, append, term);
          _this.async = null;
        }
      });
  };
  View.prototype.nextPage = function() {
    if (this.morePages) {
      this.page++;
      this.fetch(this.filter.value, true);
    }
  };
  return View;
})();

var view = new View();
//# sourceMappingURL=main.js.map
