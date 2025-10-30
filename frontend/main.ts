import "vite/modulepreload-polyfill";
import "./css/gps.css";
import "./css/autocomplete.css";
import "./css/project.css";
import "./css/main.css";

import { AutocompleteView } from "./autocomplete";
import { exists } from "./util";
import { DropdownView } from "./dropdown";
import { EmailAddressView } from "./emailaddress";
import { ReceiptsView } from "./receipts";

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
