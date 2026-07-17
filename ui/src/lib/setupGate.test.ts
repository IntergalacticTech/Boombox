import { afterEach, describe, expect, it, vi } from 'vitest'
import { redirectToSetupIfIncomplete } from './setupGate'

function stubLocation(hostname: string, pathname = '/') {
  const replace = vi.fn()
  Object.defineProperty(window, 'location', {
    value: { hostname, pathname, replace },
    writable: true,
  })
  return replace
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('redirectToSetupIfIncomplete', () => {
  it('redirects the kiosk to /setup/ when setup is incomplete', async () => {
    const replace = stubLocation('localhost')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ complete: false }),
    }))
    const did = await redirectToSetupIfIncomplete()
    expect(did).toBe(true)
    expect(replace).toHaveBeenCalledWith('/setup/')
  })

  it('does not redirect when setup is complete', async () => {
    const replace = stubLocation('localhost')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ complete: true }),
    }))
    expect(await redirectToSetupIfIncomplete()).toBe(false)
    expect(replace).not.toHaveBeenCalled()
  })

  it('never redirects a LAN (non-localhost) client', async () => {
    const replace = stubLocation('192.168.1.81')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    expect(await redirectToSetupIfIncomplete()).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(replace).not.toHaveBeenCalled()
  })

  it('fails open (no redirect) when the setup API is unreachable', async () => {
    stubLocation('localhost')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('conn refused')))
    expect(await redirectToSetupIfIncomplete()).toBe(false)
  })

  it('does not loop when already on /setup', async () => {
    const replace = stubLocation('localhost', '/setup/')
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    expect(await redirectToSetupIfIncomplete()).toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(replace).not.toHaveBeenCalled()
  })
})
