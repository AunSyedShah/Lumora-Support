import { useEffect, useState } from 'react'

import { api } from '../api/client'
import { humanize } from './labels'

/*
 * Category / subcategory / department names come from the live catalog (they can be changed
 * in Settings), loaded once and shared by every screen.
 */
let cache = null

function load() {
  cache ??= api
    .get('/catalog/taxonomy')
    .then(({ data }) => {
      const names = { category: {}, subcategory: {}, department: {} }
      data.departments.forEach((d) => (names.department[d.code] = d.name))
      data.categories.forEach((c) => {
        names.category[c.code] = c.name
        c.subcategories.forEach((s) => (names.subcategory[s.code] = s.name))
      })
      return { ...data, names }
    })
    .catch((error) => {
      cache = null // try again next time
      throw error
    })
  return cache
}

export function useTaxonomy() {
  const [taxonomy, setTaxonomy] = useState(null)
  useEffect(() => {
    let alive = true
    load()
      .then((t) => alive && setTaxonomy(t))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  const name = (kind, code) => (code ? taxonomy?.names[kind][code] || humanize(code) : '')
  return {
    taxonomy,
    categoryName: (code) => name('category', code),
    subcategoryName: (code) => name('subcategory', code),
    departmentName: (code) => name('department', code),
  }
}

/** After an admin edits the catalog. */
export function refreshTaxonomy() {
  cache = null
}
