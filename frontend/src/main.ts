import {AutocompleteView} from './autocomplete';
import {exists} from './util';
import {DropdownView} from './dropdown';
import {EmailAddressView} from './emailaddress';
import {ReceiptsView} from './receipts';
import {PlansView} from './plans';

if (exists('_id-profDropdown')) {
  // Dropdown view;
  new DropdownView();
}

if (exists('_id-autocomplete')) {
  // Autocomplete page.
  new AutocompleteView();
}

if (exists('_id-resendVerification')) {
  // E-mail address page.
  new EmailAddressView();
}

if (exists('_id-receiptsTable')) {
  // Receipts page.
  new ReceiptsView();
}

if (exists('id_stripe_pk')) {
  // Stripe and plans pages.
  new PlansView();
}
