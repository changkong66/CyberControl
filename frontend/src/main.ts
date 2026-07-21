import { createApp } from "vue"
import { createPinia } from "pinia"

import App from "./App.vue"
import { createWorkbenchRouter } from "./app/router"
import { appServicesKey, createAppServices } from "./app/services"
import { i18n } from "./i18n"
import "./styles.css"

const application = createApp(App)
const pinia = createPinia()
const router = createWorkbenchRouter(pinia)

application.use(pinia)
application.use(i18n)
application.use(router)
application.provide(appServicesKey, createAppServices(pinia))
application.mount("#app")
