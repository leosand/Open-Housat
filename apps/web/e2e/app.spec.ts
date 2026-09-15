import { expect, test } from '@playwright/test'

// E2E hors-ligne : l'API n'est pas demarree, on verifie le rendu et la remontee d'erreur.
test('accueil : titre et formulaire de creation visibles', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /Housat/i })).toBeVisible()
  await expect(page.getByRole('button', { name: /Creer le chantier/i })).toBeVisible()
})

test('soumission sans API : erreur visible via role=alert', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Nom').fill('Parcelle E2E')
  await page.getByRole('button', { name: /Creer le chantier/i }).click()
  await expect(page.getByRole('alert')).toBeVisible()
})
