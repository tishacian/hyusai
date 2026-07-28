# Remote Access and VPN

## 1. Eligibility

Remote access is granted per role, not per person. Roles eligible for remote
access are listed in the access matrix maintained by Network and Infrastructure.
A request outside those roles requires the approval of the requester's director.

Contractors are granted remote access for the duration of their contract, capped
at 12 months, and are re-approved at each renewal.

## 2. Requesting access

Access is requested through the service desk and approved by the line manager.
The target is 2 working days from approval to a working connection. Requests
that also need a corporate laptop follow the equipment lead time, which is
longer and is stated at the time of the request.

## 3. Connecting

The client is pre-installed on corporate laptops. Sign-in uses the corporate
account with MFA. Access from a personal device is limited to the browser
portal: the full tunnel is refused on unmanaged devices.

Split tunnelling is enabled: traffic to Nawa applications goes through the
tunnel, general internet traffic does not. Users must not disable it — doing so
routes personal traffic through the corporate network and is a policy breach.

## 4. Session limits

A session disconnects after 12 hours, and after 30 minutes of inactivity.
Reconnecting requires the account password and a factor. Concurrent sessions
from two different countries are blocked automatically and raise a security
alert.

## 5. Common problems

**The connection is refused immediately.** In almost all cases the account
password has expired. An expired password authenticates on the internal network,
where the sign-in prompt renews it, but is refused by remote access. The user
must change the password from a site or through the browser portal.

**The connection drops every few minutes.** Usually the local network, not the
tunnel: mobile hotspots and hotel networks that renew their address aggressively
are the common cause.

**Applications are slow but the connection holds.** Check whether split
tunnelling has been disabled, which sends everything through the tunnel.

**The client says the certificate is not valid.** The device clock is wrong, or
the device has not been on the corporate network for more than 90 days and its
certificate has expired. The device must be brought to a site, or re-enrolled.

## 6. Countries and travel

Remote access is available from any country except those on the restricted list
maintained by the IT Security Office. Travel to a restricted country requires a
travel account requested at least 5 working days in advance; the standard
account is suspended for the duration of the trip.

## 7. Leavers

Remote access is revoked at the end of the last working day, before the account
itself is disabled. The line manager is responsible for stating the last working
day at the time the departure is notified.

## Document control

Document owner: Network and Infrastructure · Version 4.1 · Effective 1 February 2026
Applies to: staff and approved contractors working outside a Nawa site
Sample content prepared for the WE preview workspace.
