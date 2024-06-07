import { d, show, hide, on } from "./util";

export class ManageTableView {
  readonly shim = d("_id-shim");
  readonly selects = Array.from(
    document.getElementsByClassName("_cls-roleSelect"),
  ) as HTMLElement[];
  readonly dropdowns = this.selects.map(
    (select) => select.nextElementSibling,
  ) as HTMLElement[];
  public hideAction: () => void | null = null;

  constructor() {
    this.selects.forEach((select, i) => {
      const dropdown = this.dropdowns[i];
      on(select, "click", () => {
        show(dropdown);
        show(this.shim);
        this.hideAction = () => {
          hide(dropdown);
          hide(this.shim);
        };
      });
      on(dropdown.querySelector("._cls-selected"), "click", () => {
        this.hide();
      });
    });

    on(this.shim, "click", () => {
      this.hide();
    });
  }

  hide() {
    if (this.hideAction != null) {
      this.hideAction();
      this.hideAction = null;
    }
  }
}
