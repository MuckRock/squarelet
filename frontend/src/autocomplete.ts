import { fetchUrl, d, on } from "./util";

const SCROLL_BUFFER = 40;

export class AutocompleteView {
  filter = d("_id-filter") as HTMLInputElement;
  close = d("_id-close");
  results = d("_id-results");
  page = 1;
  morePages = true;

  currentSearch = "";
  currentPage = 1;

  async: Promise<any> | null = null;

  constructor() {
    on(this.close, "click", () => {
      this.filter.value = "";
      this.page = 1;
      this.morePages = true;
      this.fetch("");
    });

    on(this.filter, "input", () => {
      this.resetAsync();
      this.page = 1;
      this.morePages = true;
      this.fetch(this.filter.value);
    });

    on(this.results, "scroll", () => {
      const position = this.results.scrollTop + this.results.offsetHeight;
      if (
        this.page == this.currentPage &&
        position > this.results.scrollHeight - SCROLL_BUFFER
      ) {
        this.nextPage();
      }
    });
  }

  resetAsync() {
    this.async = null;
  }

  clearResults() {
    while (this.results.firstChild)
      this.results.removeChild(this.results.firstChild);
  }

  render(json: any, append: boolean, term: string = "") {
    if (!append) {
      this.clearResults();
    }
    for (const result of json) {
      this.addResult(result.name, result.slug, result.avatar, term);
    }

    if (this.results.scrollHeight < this.results.offsetHeight + SCROLL_BUFFER) {
      this.nextPage();
    }
  }

  addResult(
    text: string,
    link: string,
    avatarUrl: string,
    highlight: string = ""
  ) {
    const a = document.createElement("a");
    a.href = link;
    const div = document.createElement("div");
    div.className = "_cls-result";

    const avatar = document.createElement("div");
    avatar.className = "_cls-inlineAvatar";
    const avatarImg = document.createElement("img");
    avatarImg.src = avatarUrl;
    avatarImg.width = 22;
    avatarImg.height = 22;
    avatar.appendChild(avatarImg);
    div.appendChild(avatar);

    if (highlight == "") {
      const span = document.createElement("span");
      span.textContent = text;
      div.appendChild(span);
    } else {
      const lowerHighlight = highlight.toLowerCase();
      let lowerText = text.toLowerCase();
      while (true) {
        let i = lowerText.indexOf(lowerHighlight);
        if (i != -1) {
          const normal = document.createElement("span");
          normal.textContent = text.substring(0, i);

          div.appendChild(normal);

          const bold = document.createElement("b");
          bold.textContent = text.substr(i, highlight.length);

          text = text.substr(i + highlight.length);
          lowerText = lowerText.substr(i + highlight.length);

          div.appendChild(bold);
        } else {
          const normal = document.createElement("span");
          normal.textContent = text;

          div.appendChild(normal);
          break;
        }
      }
    }
    a.appendChild(div);
    this.results.appendChild(a);
  }

  fetch(term: string, append = false) {
    if (!append) {
      // Scroll back to the top on new query
      this.results.scrollTop = 0;
    }
    const page = this.page;
    this.currentSearch = term;
    this.async = fetchUrl(`autocomplete?q=${term}&page=${page}`).then(
      (response) => {
        const json = JSON.parse(response);
        if (this.currentSearch == term && this.page == page) {
          const results = json.data;
          this.currentPage = page;
          if (results.length == 0) {
            this.morePages = false;
          }
          this.render(results, append, term);
          this.async = null;
        }
      }
    );
  }

  nextPage() {
    if (this.morePages) {
      this.page++;
      this.fetch(this.filter.value, true);
    }
  }
}

export class Controller {}
