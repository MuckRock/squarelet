import "@/css/login.css";

import { initLoginForm } from "@/login_form";

const form = document.querySelector<HTMLFormElement>("#login_form");
if (form) initLoginForm(form);
