// Concise get element by ID and assume it exists.
function d(id) {
    return document.getElementById(id);
}
function exists(id) {
    return document.getElementById(id) != null;
}
// Set event listener
function on(element, event, fn) {
    if (Array.isArray(event)) {
        event.forEach(function (evt) { return element.addEventListener(evt, fn, false); });
    }
    else {
        element.addEventListener(event, fn, false);
    }
}
// Fetch a URL
function fetch(url, method) {
    if (method === void 0) { method = 'GET'; }
    return new Promise(function (resolve, reject) {
        var http = new XMLHttpRequest();
        http.onload = function () {
            var status = http.status;
            if (status >= 200 && status < 300) {
                resolve(http.responseText);
            }
            else {
                reject(status + ": " + http.responseText);
            }
        };
        http.open(method, url);
        http.send();
    });
}
// Show/hide elements.
function show(elem) {
    elem.classList.remove('_cls-hide');
}
function hide(elem) {
    elem.classList.add('_cls-hide');
}

var SCROLL_BUFFER = 40;
var AutocompleteView = /** @class */ (function () {
    function AutocompleteView() {
        var _this = this;
        this.filter = d('_id-filter');
        this.close = d('_id-close');
        this.results = d('_id-results');
        this.page = 1;
        this.morePages = true;
        this.currentSearch = '';
        this.currentPage = 1;
        this.async = null;
        on(this.close, 'click', function () {
            _this.filter.value = '';
            _this.page = 1;
            _this.morePages = true;
            _this.fetch('');
        });
        on(this.filter, 'input', function () {
            _this.resetAsync();
            _this.page = 1;
            _this.morePages = true;
            _this.fetch(_this.filter.value);
        });
        on(this.results, 'scroll', function () {
            var position = _this.results.scrollTop + _this.results.offsetHeight;
            if (_this.page == _this.currentPage &&
                position > _this.results.scrollHeight - SCROLL_BUFFER) {
                _this.nextPage();
            }
        });
    }
    AutocompleteView.prototype.resetAsync = function () {
        this.async = null;
    };
    AutocompleteView.prototype.clearResults = function () {
        while (this.results.firstChild)
            this.results.removeChild(this.results.firstChild);
    };
    AutocompleteView.prototype.render = function (json, append, term) {
        if (term === void 0) { term = ''; }
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
    AutocompleteView.prototype.addResult = function (text, link, avatarUrl, highlight) {
        if (highlight === void 0) { highlight = ''; }
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
        }
        else {
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
                }
                else {
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
    AutocompleteView.prototype.fetch = function (term, append) {
        var _this = this;
        if (append === void 0) { append = false; }
        if (!append) {
            // Scroll back to the top on new query
            this.results.scrollTop = 0;
        }
        var page = this.page;
        this.currentSearch = term;
        this.async = fetch("autocomplete?q=" + term + "&page=" + page).then(function (response) {
            var json = JSON.parse(response);
            if (_this.currentSearch == term && _this.page == page) {
                var results = json.data;
                _this.currentPage = page;
                if (results.length == 0) {
                    _this.morePages = false;
                }
                _this.render(results, append, term);
                _this.async = null;
            }
        });
    };
    AutocompleteView.prototype.nextPage = function () {
        if (this.morePages) {
            this.page++;
            this.fetch(this.filter.value, true);
        }
    };
    return AutocompleteView;
}());

var DropdownView = /** @class */ (function () {
    function DropdownView() {
        var _this = this;
        this.dropdown = d('_id-profDropdown');
        this.contents = d('_id-dropdownContents');
        this.shim = d('_id-shim');
        this.hidden = true;
        on(this.dropdown, 'click', function () {
            if (_this.hidden) {
                _this.show();
            }
            else {
                _this.hide();
            }
        });
        on(this.shim, 'click', function () {
            _this.hide();
        });
    }
    DropdownView.prototype.show = function () {
        this.hidden = false;
        this.dropdown.classList.add('_cls-active');
        show(this.contents);
        show(this.shim);
    };
    DropdownView.prototype.hide = function () {
        this.hidden = true;
        this.dropdown.classList.remove('_cls-active');
        hide(this.contents);
        hide(this.shim);
    };
    return DropdownView;
}());

// TODO: route email address udpate view through here

var ReceiptsView = /** @class */ (function () {
    function ReceiptsView() {
        var _this = this;
        this.expandActions = Array.from(document.getElementsByClassName('_cls-expandAction'));
        this.expanded = false;
        this.expandActions.forEach(function (action) {
            on(action, 'click', function () {
                if (!_this.expanded) {
                    _this.expanded = true;
                    action.firstChild.textContent = 'Collapse';
                    var row = action.closest('._cls-manageRow');
                    var newRow = document.createElement('div');
                    newRow.className = '_cls-manageRow _cls-iframeRow';
                    var iframe = document.createElement('iframe');
                    iframe.src = "/organizations/~charge/" + action.dataset['charge'] + "/";
                    newRow.appendChild(iframe);
                    row.parentElement.insertBefore(newRow, row.nextSibling);
                }
                else {
                    _this.expanded = false;
                    action.firstChild.textContent = 'Expand';
                    var row = action.closest('._cls-manageRow');
                    var iframeRow = row.nextSibling;
                    iframeRow.parentElement.removeChild(iframeRow);
                }
            });
        });
    }
    return ReceiptsView;
}());

/// <reference types="stripe-v3" />
// Style for the Stripe card element.
var STRIPE_STYLE = {
    base: {
        color: '#3F3F3F',
        fontSize: '18px',
        fontFamily: 'system-ui, sans-serif',
        fontSmoothing: 'antialiased',
        '::placeholder': {
            color: '#899194',
        },
    },
    invalid: {
        color: '#e5424d',
        ':focus': {
            color: '#303238',
        },
    },
};
/**
 * Set up and handle reactive views related to paid plans.
 */
var PlansView = /** @class */ (function () {
    function PlansView() {
        this.stripePk = d('id_stripe_pk'); // hidden Stripe key
        this.planInput = d('id_plan');
        this.ucofInput = d('id_use_card_on_file');
        this.ccFieldset = d('_id-cardFieldset');
        this.planInfoElem = d('_id-planInfo'); // Pane to show plan information
        this.planProjection = d('_id-planProjection'); // Plan projection information
        this.cardContainer = d('card-container'); // Credit card container.
        this.receiptEmails = d('_id-receiptEmails');
        this.totalCost = d('_id-totalCost');
        this.costBreakdown = d('_id-costBreakdown');
        this.maxUsersElem = d('id_max_users');
        this.planInfo = JSON.parse(this.planInfoElem.textContent);
        this.setupMaxUsersField();
        this.setupCardOnFileField();
        this.setupReceiptEmails();
        this.setupStripe();
        this.updateAll();
    }
    /**
     * Resize the receipt emails to match the text content.
     */
    PlansView.prototype.receiptResize = function () {
        // Set a small initial height to derive the scroll height.
        this.receiptEmails.style.height = '5px';
        this.receiptEmails.style.height = this.receiptEmails.scrollHeight + 'px';
    };
    /**
     * Returns the currently selected plan information.
     */
    PlansView.prototype.getPlan = function () {
        return this.planInfo[this.planInput.value];
    };
    /**
     * Update the total cost breakdown text.
     * TODO: figure out i18n for these strings
     */
    PlansView.prototype.updateTotalCost = function () {
        var plan = this.getPlan();
        var cost = "" + (plan.base_price +
            (this.maxUsers - plan.minimum_users) * plan.price_per_user);
        var costFormatted = "$" + cost;
        this.totalCost.textContent = costFormatted;
        var costBreakdownFormatted = "$" + plan.base_price + " (base price)";
        if (this.maxUsers != 0) {
            if (this.maxUsers - plan.minimum_users == 0) {
                costBreakdownFormatted += " with " + plan.minimum_users + " user" + (plan.minimum_users != 1 ? 's' : '') + " included";
                if (plan.price_per_user != 0) {
                    costBreakdownFormatted += " ($" + plan.price_per_user + " per additional user)";
                }
            }
            else {
                costBreakdownFormatted += " with " + plan.minimum_users + " user" + (plan.minimum_users != 1 ? 's' : '') + " included and " + (this.maxUsers - plan.minimum_users) + " extra users at $" + plan.price_per_user + " each";
            }
        }
        this.costBreakdown.textContent = costBreakdownFormatted;
    };
    /**
     * Handle updates to the plan selection.
     */
    PlansView.prototype.updatePlanInput = function () {
        var plan = this.getPlan();
        var isFreePlan = isFree(plan);
        this.updateTotalCost();
        // TODO: use util function for this display logic.
        if (isFreePlan) {
            if (this.ccFieldset != null) {
                this.ccFieldset.style.display = 'none';
            }
            if (this.planProjection != null) {
                this.planProjection.style.display = 'none';
            }
        }
        else {
            if (this.ccFieldset != null) {
                this.ccFieldset.style.display = '';
            }
            if (this.planProjection != null) {
                this.planProjection.style.display = '';
            }
        }
        this.updateAll(false);
    };
    /**
     * Handle changes to the max users element.
     */
    PlansView.prototype.updateMaxUsers = function () {
        if (this.maxUsersElem == null)
            return;
        this.maxUsers = parseInt(this.maxUsersElem.value);
        var minUsers = this.getPlan().minimum_users;
        this.maxUsersElem.min = "" + minUsers;
        if (this.maxUsers < minUsers) {
            this.maxUsersElem.value = "" + minUsers;
            this.maxUsers = minUsers;
        }
    };
    /**
     * Handle changes to the saved credit card selection.
     */
    PlansView.prototype.updateSavedCC = function () {
        if (this.ucofInput == null) {
            if (isFree(this.getPlan())) {
                if (this.cardContainer != null) {
                    this.cardContainer.style.display = 'none';
                }
            }
            else {
                if (this.cardContainer != null) {
                    this.cardContainer.style.display = '';
                }
            }
            return;
        }
        var ucofInput = document.querySelector('input[name=use_card_on_file]:checked');
        if (ucofInput.value == 'True') {
            if (this.cardContainer != null) {
                // TODO: Use utility hide function
                this.cardContainer.style.display = 'none';
            }
        }
        else {
            if (this.cardContainer != null) {
                this.cardContainer.style.display = '';
            }
        }
    };
    /**
     * Updates the max users, saved credit card, and plan input selections simultaneously.
     * This method is used to safely ensure changes are recognized by all reactive
     * components.
     * @param updatePlanInput Whether to also update the plan input. This is set to false
     * when the plan input calls this method to avoid infinite loops.
     */
    PlansView.prototype.updateAll = function (updatePlanInput) {
        if (updatePlanInput === void 0) { updatePlanInput = true; }
        this.updateMaxUsers();
        this.updateSavedCC();
        if (updatePlanInput)
            this.updatePlanInput();
    };
    /**
     * Set up event listeners and variables related to the max users setting.
     */
    PlansView.prototype.setupMaxUsersField = function () {
        var _this = this;
        if (exists('id_max_users')) {
            // Handle reactive max user updates if field is defined.
            var maxUsersElem = this.maxUsersElem;
            this.maxUsers = parseInt(maxUsersElem.value);
            on(maxUsersElem, 'input', function () {
                _this.updateAll();
            });
        }
        else {
            this.maxUsers = 1;
        }
    };
    /**
     * Set up event listeners and variables related to the card on file field.
     */
    PlansView.prototype.setupCardOnFileField = function () {
        var _this = this;
        if (exists('id_use_card_on_file')) {
            on(this.ucofInput, 'input', function () {
                _this.updateAll();
            });
        }
    };
    /**
     * Set up event listeners and variables related to the receipt emails field.
     */
    PlansView.prototype.setupReceiptEmails = function () {
        var _this = this;
        if (this.receiptEmails == null)
            return;
        // Make receipt emails field auto-resize.
        this.receiptEmails.rows = 2;
        on(this.receiptEmails, 'input', function () { return _this.receiptResize(); });
        this.receiptResize();
    };
    /**
     * Set up event listeners and variables related to Stripe.
     */
    PlansView.prototype.setupStripe = function () {
        var _this = this;
        if (exists('card-element')) {
            var stripe_1 = Stripe(this.stripePk.value);
            var elements = stripe_1.elements();
            // Decorate card.
            var card_1 = elements.create('card', { style: STRIPE_STYLE });
            card_1.mount('#card-element');
            card_1.addEventListener('change', function (event) {
                var changeEvent = event;
                // Show Stripe errors.
                var displayError = document.getElementById('card-errors');
                if (changeEvent.error) {
                    displayError.textContent = changeEvent.error.message;
                }
                else {
                    displayError.textContent = '';
                }
            });
            // We don't want the browser to fill this in with old values
            document.getElementById('id_stripe_token').value = '';
            // only show payment fields if needed
            this.planInput.addEventListener('input', function () {
                _this.updateAll();
            });
            // Create a token or display an error when the form is submitted.
            var form = document.getElementById('stripe-form');
            form.addEventListener('submit', function (event) {
                var ucofInput = document.querySelector('input[name=use_card_on_file]:checked');
                var useCardOnFile = ucofInput != null && ucofInput.value == 'True';
                var plan = _this.getPlan();
                var isFreePlan = isFree(plan);
                if (!useCardOnFile && !isFreePlan) {
                    event.preventDefault();
                    stripe_1.createToken(card_1).then(function (result) {
                        if (result.error) {
                            // Inform the customer that there was an error.
                            var errorElement = document.getElementById('card-errors');
                            errorElement.textContent = result.error.message;
                        }
                        else {
                            // Send the token to your server.
                            stripeTokenHandler(result.token);
                        }
                    });
                }
            });
        }
    };
    return PlansView;
}());
/**
 * Set the hidden Stripe token input to reflect the given token, then submit the form.
 * @param token
 */
function stripeTokenHandler(token) {
    // Insert the token ID into the form so it gets submitted to the server
    var hiddenInput = document.getElementById('id_stripe_token');
    hiddenInput.value = token.id;
    // Submit the form
    document.getElementById('stripe-form').submit();
}
/**
 * Return whether the specified plan is free.
 */
function isFree(plan) {
    return plan.base_price == 0 && plan.price_per_user == 0 && plan.minimum_users == 1;
}

var ManageTableView = /** @class */ (function () {
    function ManageTableView() {
        var _this = this;
        this.shim = d('_id-shim');
        this.selects = Array.from(document.getElementsByClassName('_cls-roleSelect'));
        this.dropdowns = this.selects.map(function (select) { return select.nextElementSibling; });
        this.hideAction = null;
        this.selects.forEach(function (select, i) {
            var dropdown = _this.dropdowns[i];
            on(select, 'click', function () {
                show(dropdown);
                show(_this.shim);
                _this.hideAction = function () {
                    hide(dropdown);
                    hide(_this.shim);
                };
            });
            on(dropdown.querySelector('._cls-selected'), 'click', function () {
                _this.hide();
            });
        });
        on(this.shim, 'click', function () {
            _this.hide();
        });
    }
    ManageTableView.prototype.hide = function () {
        if (this.hideAction != null) {
            this.hideAction();
            this.hideAction = null;
        }
    };
    return ManageTableView;
}());

if (exists('_id-profDropdown')) {
    // Dropdown view;
    new DropdownView();
}
if (exists('_id-autocomplete')) {
    // Autocomplete page.
    new AutocompleteView();
}
if (exists('_id-manageTable')) {
    // Manage members view.
    //new ManageTableView();
}
if (exists('_id-resendVerification')) ;
if (exists('_id-receiptsTable')) {
    // Receipts page.
    new ReceiptsView();
}
if (exists('id_stripe_pk')) {
    // Stripe and plans pages.
    new PlansView();
}
//# sourceMappingURL=main.js.map
