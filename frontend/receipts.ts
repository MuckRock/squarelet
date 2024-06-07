import { on } from "./util";

export class ReceiptsView {
  expandActions: HTMLElement[] = Array.from(
    document.getElementsByClassName("_cls-expandAction"),
  ) as HTMLElement[];
  expanded = false;

  constructor() {
    this.expandActions.forEach((action) => {
      on(action, "click", () => {
        if (!this.expanded) {
          this.expanded = true;
          action.firstChild.textContent = "Collapse";
          const row = action.closest("._cls-manageRow") as HTMLElement;
          const newRow = document.createElement("div");
          newRow.className = "_cls-manageRow _cls-iframeRow";

          const iframe = document.createElement("iframe");
          iframe.src = `/organizations/~charge/${action.dataset["charge"]}/`;
          newRow.appendChild(iframe);

          row.parentElement.insertBefore(newRow, row.nextSibling);
        } else {
          this.expanded = false;
          action.firstChild.textContent = "Expand";
          const row = action.closest("._cls-manageRow") as HTMLElement;
          const iframeRow = row.nextSibling;
          iframeRow.parentElement.removeChild(iframeRow);
        }
      });
    });
  }
}
