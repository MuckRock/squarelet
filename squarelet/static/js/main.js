function f(b){return document.getElementById(b)}function h(b){return null!=document.getElementById(b)}function l(b,a,c){Array.isArray(a)?a.forEach(function(a){return b.addEventListener(a,c,!1)}):b.addEventListener(a,c,!1)}function n(b,a){void 0===a&&(a="GET");return new Promise(function(c,e){var d=new XMLHttpRequest;d.onload=function(){var a=d.status;200<=a&&300>a?c(d.responseText):e(a+": "+d.responseText)};d.open(a,b);d.send()})}
var p=function(){function b(){var a=this;this.filter=f("_id-filter");this.close=f("_id-close");this.results=f("_id-results");this.page=1;this.morePages=!0;this.currentSearch="";this.currentPage=1;this.async=null;l(this.close,"click",function(){a.filter.value="";a.page=1;a.morePages=!0;a.fetch("")});l(this.filter,"input",function(){a.resetAsync();a.page=1;a.morePages=!0;a.fetch(a.filter.value)});l(this.results,"scroll",function(){var c=a.results.scrollTop+a.results.offsetHeight;a.page==a.currentPage&&
c>a.results.scrollHeight-40&&a.nextPage()})}b.prototype.resetAsync=function(){this.async=null};b.prototype.clearResults=function(){for(;this.results.firstChild;)this.results.removeChild(this.results.firstChild)};b.prototype.render=function(a,c,b){void 0===b&&(b="");c||this.clearResults();for(c=0;c<a.length;c++){var d=a[c];this.addResult(d.name,d.slug,d.avatar,b)}this.results.scrollHeight<this.results.offsetHeight+40&&this.nextPage()};b.prototype.addResult=function(a,c,b,d){void 0===d&&(d="");var e=
document.createElement("a");e.href=c;c=document.createElement("div");c.className="_cls-result";var k=document.createElement("div");k.className="_cls-inlineAvatar";var g=document.createElement("img");g.src=b;g.width=22;g.height=22;k.appendChild(g);c.appendChild(k);if(""==d)d=document.createElement("span"),d.textContent=a,c.appendChild(d);else for(b=d.toLowerCase(),k=a.toLowerCase();;)if(g=k.indexOf(b),-1!=g){var m=document.createElement("span");m.textContent=a.substring(0,g);c.appendChild(m);m=document.createElement("b");
m.textContent=a.substr(g,d.length);a=a.substr(g+d.length);k=k.substr(g+d.length);c.appendChild(m)}else{m=document.createElement("span");m.textContent=a;c.appendChild(m);break}e.appendChild(c);this.results.appendChild(e)};b.prototype.fetch=function(a,b){var c=this;void 0===b&&(b=!1);b||(this.results.scrollTop=0);var d=this.page;this.currentSearch=a;this.async=n("autocomplete?q="+a+"&page="+d).then(function(e){e=JSON.parse(e);c.currentSearch==a&&c.page==d&&(e=e.data,c.currentPage=d,0==e.length&&(c.morePages=
!1),c.render(e,b,a),c.async=null)})};b.prototype.nextPage=function(){this.morePages&&(this.page++,this.fetch(this.filter.value,!0))};return b}(),q=function(){function b(){var a=this;this.dropdown=f("_id-profDropdown");this.contents=f("_id-dropdownContents");this.shim=f("_id-shim");this.hidden=!0;l(this.dropdown,"click",function(){a.hidden?a.show():a.hide()});l(this.shim,"click",function(){a.hide()})}b.prototype.show=function(){this.hidden=!1;this.dropdown.classList.add("_cls-active");this.contents.classList.remove("_cls-hide");
this.shim.classList.remove("_cls-hide")};b.prototype.hide=function(){this.hidden=!0;this.dropdown.classList.remove("_cls-active");this.contents.classList.add("_cls-hide");this.shim.classList.add("_cls-hide")};return b}();
function r(){var b=this;this.expandActions=Array.from(document.getElementsByClassName("_cls-expandAction"));this.expanded=!1;this.expandActions.forEach(function(a){l(a,"click",function(){if(b.expanded)b.expanded=!1,a.firstChild.textContent="Expand",c=a.closest("._cls-manageRow"),c=c.nextSibling,c.parentElement.removeChild(c);else{b.expanded=!0;a.firstChild.textContent="Collapse";var c=a.closest("._cls-manageRow"),e=document.createElement("div");e.className="_cls-manageRow _cls-iframeRow";var d=document.createElement("iframe");
d.src="/organizations/~charge/"+a.dataset.charge+"/";e.appendChild(d);c.parentElement.insertBefore(e,c.nextSibling)}})})}
var t=window.Stripe,u={base:{color:"#3F3F3F",fontSize:"18px",fontFamily:"system-ui, sans-serif",fontSmoothing:"antialiased","::placeholder":{color:"#899194"}},invalid:{color:"#e5424d",":focus":{color:"#303238"}}},w=function(){function b(){this.stripePk=f("id_stripe_pk");this.planInput=f("id_plan");this.ucofInput=f("id_use_card_on_file");this.rcofInput=f("id_remove_card_on_file");this.ccFieldset=f("_id-cardFieldset");this.removeCardFieldset=f("_id-removeCardFieldset");this.planInfoElem=f("_id-planInfo");
this.planProjection=f("_id-planProjection");this.cardContainer=f("card-container");this.receiptEmails=f("_id-receiptEmails");this.totalCost=f("_id-totalCost");this.costBreakdown=f("_id-costBreakdown");this.maxUsersElem=f("id_max_users");this.planInfo=JSON.parse(this.planInfoElem.textContent);this.setupMaxUsersField();this.setupCardOnFileField();this.setupReceiptEmails();this.setupStripe();this.updateAll()}b.prototype.receiptResize=function(){this.receiptEmails.style.height="5px";this.receiptEmails.style.height=
this.receiptEmails.scrollHeight+"px"};b.prototype.getPlan=function(){return this.planInfo[this.planInput.value]||this.planInfo[""]};b.prototype.updateTotalCost=function(){if(null!=this.totalCost){var a=this.getPlan();this.totalCost.textContent="$"+(a.base_price+(this.maxUsers-a.minimum_users)*a.price_per_user)+" / "+(a.annual?"year":"month");var b="$"+a.base_price+" (base price)";0!=this.maxUsers&&(0==this.maxUsers-a.minimum_users?(b+=" with "+a.minimum_users+" user"+(1!=a.minimum_users?"s":"")+" included",
0!=a.price_per_user&&(b+=" ($"+a.price_per_user+" per additional user)")):b+=" with "+a.minimum_users+" user"+(1!=a.minimum_users?"s":"")+" included and "+(this.maxUsers-a.minimum_users)+" extra users at $"+a.price_per_user+" each");this.costBreakdown.textContent=b}};b.prototype.updatePlanInput=function(){var a=this.getPlan();this.updateTotalCost();v(a)?(null!=this.ccFieldset&&(this.ccFieldset.style.display=""),null!=this.removeCardFieldset&&(this.removeCardFieldset.style.display="none")):(null!=
this.ccFieldset&&(this.ccFieldset.style.display="none"),null!=this.removeCardFieldset&&(this.removeCardFieldset.style.display=""));0==a.base_price&&0==a.price_per_user?null!=this.planProjection&&(this.planProjection.style.display="none"):null!=this.planProjection&&(this.planProjection.style.display="");this.updateAll(!1)};b.prototype.updateMaxUsers=function(){if(null!=this.maxUsersElem){this.maxUsers=parseInt(this.maxUsersElem.value);var a=parseInt(this.maxUsersElem.min);this.maxUsers<a&&(this.maxUsersElem.value=
""+a,this.maxUsers=a)}};b.prototype.updateSavedCC=function(){null==this.ucofInput?v(this.getPlan())?null!=this.cardContainer&&(this.cardContainer.style.display=""):null!=this.cardContainer&&(this.cardContainer.style.display="none"):"True"==document.querySelector("input[name=use_card_on_file]:checked").value?null!=this.cardContainer&&(this.cardContainer.style.display="none"):null!=this.cardContainer&&(this.cardContainer.style.display="")};b.prototype.updateAll=function(a){void 0===a&&(a=!0);this.updateMaxUsers();
this.updateSavedCC();a&&this.updatePlanInput()};b.prototype.setupMaxUsersField=function(){var a=this;if(h("id_max_users")){var b=this.maxUsersElem;this.maxUsers=parseInt(b.value);l(b,"blur",function(){a.updateAll()})}else this.maxUsers=this.getPlan().minimum_users};b.prototype.setupCardOnFileField=function(){var a=this;h("id_use_card_on_file")&&l(this.ucofInput,"input",function(){a.updateAll()})};b.prototype.setupReceiptEmails=function(){var a=this;null!=this.receiptEmails&&(this.receiptEmails.rows=
2,l(this.receiptEmails,"input",function(){return a.receiptResize()}),this.receiptResize())};b.prototype.setupStripe=function(){var a=this;if(h("card-element")){var b=t(this.stripePk.value),e=b.elements().create("card",{style:u});e.mount("#card-element");e.addEventListener("change",function(a){document.getElementById("card-errors").textContent=a.error?a.error.message:""});document.getElementById("id_stripe_token").value="";this.planInput.addEventListener("input",function(){a.updateAll()});document.getElementById("stripe-form").addEventListener("submit",
function(c){var d=document.querySelector("input[name=use_card_on_file]:checked");d=null!=d&&"True"==d.value;var k=a.getPlan();!d&&v(k)&&(c.preventDefault(),b.createToken(e).then(function(a){a.error?document.getElementById("card-errors").textContent=a.error.message:(a=a.token,document.getElementById("id_stripe_token").value=a.id,document.getElementById("stripe-form").submit())}))})}};return b}();function v(b){return!(0==b.base_price&&0==b.price_per_user)&&!b.annual}h("_id-profDropdown")&&new q;
h("_id-autocomplete")&&new p;h("_id-resendVerification");h("_id-receiptsTable")&&new r;h("id_stripe_pk")&&new w;
//# sourceMappingURL=main.js.map
