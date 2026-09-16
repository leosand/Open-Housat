import { expect, test } from '@playwright/test'

// E2E hors-ligne : l'API n'est pas demarree, on verifie le rendu et la remontee d'erreur.
test('accueil : titre et formulaire de creation visibles', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Housat/i })).toBeVisible()
  await expect(page.getByRole('button', { name: /Creer le chantier/i })).toBeVisible()
})

test('soumission en erreur API : erreur visible via role=alert', async ({ page }) => {
  // Deterministe : on FORCE une reponse d'erreur cote API (que l'API tourne ou non) —
  // sinon le test depend de l'environnement (echoue si une API est accessible sur :8000).
  await page.route('**/sites', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ status: 500, contentType: 'application/json',
                        body: JSON.stringify({ title: 'Erreur serveur (test E2E)' }) })
      : route.continue())
  await page.goto('/')
  await page.getByLabel('Nom').fill('Parcelle E2E')
  await page.getByRole('button', { name: /Creer le chantier/i }).click()
  await expect(page.getByRole('alert')).toBeVisible()
})
