import "vue-router"

declare module "vue-router" {
  interface RouteMeta {
    requiresAuth?: boolean
    requiredScopes?: readonly string[]
    shell?: boolean
    titleKey?: string
  }
}
