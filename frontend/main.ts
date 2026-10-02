import "vite/modulepreload-polyfill";
import "./css/gps.css";
import "./css/autocomplete.css";
import "./css/project.css";
import "./css/main.css";
import "./css/card.css";
import "./css/modal.css";
import "./css/hijack.css";

import { AutocompleteView } from "./autocomplete";
import { exists } from "./util";
import { DropdownView } from "./dropdown";
import { EmailAddressView } from "./emailaddress";
import { ReceiptsView } from "./receipts";
import { initAlerts } from "./alerts";
import { initAvatarWidgets } from "./avatar_widget";
import { initNavigation } from "./navigation";
// import {ManageTableView} from './managetable';

// Initialize alert system for progressive enhancement
initAlerts();
initNavigation();
initAvatarWidgets();

// Any element with data-confirm asks before its click goes through.
document.addEventListener("click", (e) => {
  const el = (e.target as Element).closest<HTMLElement>("[data-confirm]");
  if (el && !confirm(el.dataset.confirm)) e.preventDefault();
});

if (exists("_id-profDropdown")) {
  // Dropdown view;
  new DropdownView();
}

if (exists("_id-autocomplete")) {
  // Autocomplete page.
  new AutocompleteView();
}

// TODO(incorporate new manage table)
// if (exists('_id-manageTable')) {
//   // Manage members view.
//   new ManageTableView();
// }

if (exists("_id-resendVerification")) {
  // E-mail address page.
  new EmailAddressView();
}

if (exists("_id-receiptsTable")) {
  // Receipts page.
  new ReceiptsView();
}
