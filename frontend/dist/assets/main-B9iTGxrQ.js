(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const t of document.querySelectorAll('link[rel="modulepreload"]'))s(t);new MutationObserver(t=>{for(const i of t)if(i.type==="childList")for(const l of i.addedNodes)l.tagName==="LINK"&&l.rel==="modulepreload"&&s(l)}).observe(document,{childList:!0,subtree:!0});function r(t){const i={};return t.integrity&&(i.integrity=t.integrity),t.referrerPolicy&&(i.referrerPolicy=t.referrerPolicy),t.crossOrigin==="use-credentials"?i.credentials="include":t.crossOrigin==="anonymous"?i.credentials="omit":i.credentials="same-origin",i}function s(t){if(t.ep)return;t.ep=!0;const i=r(t);fetch(t.href,i)}})();function o(n){return document.getElementById(n)}function d(n){return document.getElementById(n)!=null}function a(n,e,r){Array.isArray(e)?e.forEach(s=>n.addEventListener(s,r,!1)):n.addEventListener(e,r,!1)}function x(n,e="GET"){return new Promise((r,s)=>{const t=new XMLHttpRequest;t.onload=()=>{const i=t.status;i>=200&&i<300?r(t.responseText):s(`${i}: ${t.responseText}`)},t.open(e,n),t.send()})}function g(n){n.classList.remove("_cls-hide")}function C(n){n.classList.add("_cls-hide")}const E=40;class w{constructor(){this.filter=o("_id-filter"),this.close=o("_id-close"),this.results=o("_id-results"),this.page=1,this.morePages=!0,this.currentSearch="",this.currentPage=1,this.async=null,a(this.close,"click",()=>{this.filter.value="",this.page=1,this.morePages=!0,this.fetch("")}),a(this.filter,"input",()=>{this.resetAsync(),this.page=1,this.morePages=!0,this.fetch(this.filter.value)}),a(this.results,"scroll",()=>{const e=this.results.scrollTop+this.results.offsetHeight;this.page==this.currentPage&&e>this.results.scrollHeight-E&&this.nextPage()})}resetAsync(){this.async=null}clearResults(){for(;this.results.firstChild;)this.results.removeChild(this.results.firstChild)}render(e,r,s=""){r||this.clearResults();for(const t of e)this.addResult(t.name,t.slug,t.avatar,s);this.results.scrollHeight<this.results.offsetHeight+E&&this.nextPage()}addResult(e,r,s,t=""){const i=document.createElement("a");i.href=r;const l=document.createElement("div");l.className="_cls-result";const c=document.createElement("div");c.className="_cls-inlineAvatar";const p=document.createElement("img");if(p.src=s,p.width=22,p.height=22,c.appendChild(p),l.appendChild(c),t==""){const m=document.createElement("span");m.textContent=e,l.appendChild(m)}else{const m=t.toLowerCase();let u=e.toLowerCase();for(;;){let h=u.indexOf(m);if(h!=-1){const f=document.createElement("span");f.textContent=e.substring(0,h),l.appendChild(f);const y=document.createElement("b");y.textContent=e.substr(h,t.length),e=e.substr(h+t.length),u=u.substr(h+t.length),l.appendChild(y)}else{const f=document.createElement("span");f.textContent=e,l.appendChild(f);break}}}i.appendChild(l),this.results.appendChild(i)}fetch(e,r=!1){r||(this.results.scrollTop=0);const s=this.page;this.currentSearch=e,this.async=x(`autocomplete?q=${e}&page=${s}`).then(t=>{const i=JSON.parse(t);if(this.currentSearch==e&&this.page==s){const l=i.data;this.currentPage=s,l.length==0&&(this.morePages=!1),this.render(l,r,e),this.async=null}})}nextPage(){this.morePages&&(this.page++,this.fetch(this.filter.value,!0))}}class v{constructor(){this.dropdown=o("_id-profDropdown"),this.contents=o("_id-dropdownContents"),this.shim=o("_id-shim"),this.hidden=!0,a(this.dropdown,"click",()=>{this.hidden?this.show():this.hide()}),a(this.shim,"click",()=>{this.hide()})}show(){this.hidden=!1,this.dropdown.classList.add("_cls-active"),g(this.contents),g(this.shim)}hide(){this.hidden=!0,this.dropdown.classList.remove("_cls-active"),C(this.contents),C(this.shim)}}class P{constructor(){this.expandActions=Array.from(document.getElementsByClassName("_cls-expandAction")),this.expanded=!1,this.expandActions.forEach(e=>{a(e,"click",()=>{if(this.expanded){this.expanded=!1,e.firstChild.textContent="Expand";const s=e.closest("._cls-manageRow").nextSibling;s.parentElement.removeChild(s)}else{this.expanded=!0,e.firstChild.textContent="Collapse";const r=e.closest("._cls-manageRow"),s=document.createElement("div");s.className="_cls-manageRow _cls-iframeRow";const t=document.createElement("iframe");t.src=`/organizations/~charge/${e.dataset.charge}/`,s.appendChild(t),r.parentElement.insertBefore(s,r.nextSibling)}})})}}const I=window.Stripe,b={base:{color:"#3F3F3F",fontSize:"18px",fontFamily:"system-ui, sans-serif",fontSmoothing:"antialiased","::placeholder":{color:"#899194"}},invalid:{color:"#e5424d",":focus":{color:"#303238"}}};class F{constructor(){this.stripePk=o("id_stripe_pk"),this.planInput=o("id_plan"),this.ucofInput=o("id_use_card_on_file"),this.rcofInput=o("id_remove_card_on_file"),this.ccFieldset=o("_id-cardFieldset"),this.removeCardFieldset=o("_id-removeCardFieldset"),this.planInfoElem=o("_id-planInfo"),this.planProjection=o("_id-planProjection"),this.cardContainer=o("card-container"),this.receiptEmails=o("_id-receiptEmails"),this.totalCost=o("_id-totalCost"),this.costBreakdown=o("_id-costBreakdown"),this.maxUsersElem=o("id_max_users"),this.planInfo=JSON.parse(this.planInfoElem.textContent),this.setupMaxUsersField(),this.setupCardOnFileField(),this.setupReceiptEmails(),this.setupStripe(),this.updateAll()}receiptResize(){this.receiptEmails.style.height="5px",this.receiptEmails.style.height=this.receiptEmails.scrollHeight+"px"}getPlan(){return this.planInfo[this.planInput.value]||this.planInfo[""]}updateTotalCost(){if(this.totalCost==null)return;const e=this.getPlan(),r=`${e.base_price+(this.maxUsers-e.minimum_users)*e.price_per_user}`,s=e.annual?"year":"month",t=`$${r} / ${s}`;this.totalCost.textContent=t;let i=`$${e.base_price} (base price)`;this.maxUsers!=0&&(this.maxUsers-e.minimum_users==0?(i+=` with ${e.minimum_users} resource block${e.minimum_users!=1?"s":""} included`,e.price_per_user!=0&&(i+=` ($${e.price_per_user} per additional resouece block)`)):i+=` with ${e.minimum_users} resource block${e.minimum_users!=1?"s":""} included and ${this.maxUsers-e.minimum_users} extra resource blocks
          at $${e.price_per_user} each`),this.costBreakdown.textContent=i}updatePlanInput(){const e=this.getPlan();this.updateTotalCost(),U(e)?(this.ccFieldset!=null&&(this.ccFieldset.style.display=""),this.removeCardFieldset!=null&&(this.removeCardFieldset.style.display="none")):(this.ccFieldset!=null&&(this.ccFieldset.style.display="none"),this.removeCardFieldset!=null&&(this.removeCardFieldset.style.display="")),_(e)?this.planProjection!=null&&(this.planProjection.style.display="none"):this.planProjection!=null&&(this.planProjection.style.display="");const r=document.querySelector("#id_max_users");if(r){const s=r.closest("fieldset"),t=document.querySelector("#hint_id_max_users");e.slug===""?s.style.display="none":e.slug=="organization"?(s.style.display="",t.textContent=`Your plan covers unlimited users.  By default, this organization plan
          includes 50 requests on MuckRock as well as 5,000 credits for
          DocumentCloud premium features, both renewed monthly on your billing
          date.  Each additional resource block above 5 will grant you another 10
          requests and 500 premium credits.`):(s.style.display="",t.textContent=`You have selected a custom plan.  Please contact a staff member for
          specific details on how many resources each resource block will
          provide.`)}this.updateAll(!1)}updateMaxUsers(){if(this.maxUsersElem==null)return;this.maxUsers=parseInt(this.maxUsersElem.value);const e=parseInt(this.maxUsersElem.min);this.maxUsers<e&&(this.maxUsersElem.value=`${e}`,this.maxUsers=e)}updateSavedCC(){if(this.ucofInput==null){this.cardContainer!=null&&(this.cardContainer.style.display="");return}document.querySelector("input[name=use_card_on_file]:checked").value=="True"&&this.ccFieldset.style.display===""?this.cardContainer!=null&&(this.cardContainer.style.display="none"):this.cardContainer!=null&&(this.cardContainer.style.display="")}updateAll(e=!0){this.updateMaxUsers(),this.updateSavedCC(),e&&this.updatePlanInput()}setupMaxUsersField(){if(d("id_max_users")){const e=this.maxUsersElem;this.maxUsers=parseInt(e.value),a(e,"blur",()=>{this.updateAll()})}else{const e=this.getPlan();this.maxUsers=e.minimum_users}}setupCardOnFileField(){d("id_use_card_on_file")&&a(this.ucofInput,"input",()=>{this.updateAll()})}setupReceiptEmails(){this.receiptEmails!=null&&(this.receiptEmails.rows=2,a(this.receiptEmails,"input",()=>this.receiptResize()),this.receiptResize())}setupStripe(){if(d("card-element")){const e=I(this.stripePk.value),s=e.elements().create("card",{style:b});s.mount("#card-element"),s.addEventListener("change",i=>{const l=i,c=document.getElementById("card-errors");l.error?c.textContent=l.error.message:c.textContent=""}),document.getElementById("id_stripe_token").value="",this.planInput.addEventListener("input",()=>{this.updateAll()}),document.getElementById("stripe-form").addEventListener("submit",i=>{const l=document.querySelector("input[name=use_card_on_file]:checked"),c=l!=null&&l.value=="True",p=this.getPlan(),m=document.querySelector("#card-element").classList.contains("StripeElement--empty");_(p)&&m||c||(i.preventDefault(),e.createToken(s).then(function(u){if(u.error){const h=document.getElementById("card-errors");h.textContent=u.error.message}else S(u.token)}))})}}}function S(n){const e=document.getElementById("id_stripe_token");e.value=n.id,document.getElementById("stripe-form").submit()}function _(n){return n.base_price==0&&n.price_per_user==0}function U(n){return!_(n)&&!n.annual}d("_id-profDropdown")&&new v;d("_id-autocomplete")&&new w;d("_id-resendVerification");d("_id-receiptsTable")&&new P;d("id_stripe_pk")&&new F;
