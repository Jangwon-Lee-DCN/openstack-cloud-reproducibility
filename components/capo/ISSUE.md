# ISSUE

CAPO `v0.14.6` asks Neutron for a single matching port with `Limit: 1`.
This Neutron deployment returns a pagination link when the result count equals
the limit. Gophercloud `v2.10.0` then fails while collecting all pages with:

`json: cannot unmarshal string into Go value of type map[string]interface {}`

The failure prevents CAPO from resolving an explicitly selected external
network.
