import { d, on, show, hide } from "./util";

export class DropdownView {
  readonly dropdown = d("_id-profDropdown");
  readonly contents = d("_id-dropdownContents");
  readonly shim = d("_id-shim");
  hidden = true;

  constructor() {
    on(this.dropdown, "click", () => {
      if (this.hidden) {
        this.show();
      } else {
        this.hide();
      }
    });

    on(this.shim, "click", () => {
      this.hide();
    });
  }

  show() {
    this.hidden = false;
    this.dropdown.classList.add("_cls-active");
    show(this.contents);
    show(this.shim);
  }

  hide() {
    this.hidden = true;
    this.dropdown.classList.remove("_cls-active");
    hide(this.contents);
    hide(this.shim);
  }
}
