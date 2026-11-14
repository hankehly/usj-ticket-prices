# USJ Ticket Prices

Tracks the published prices of Universal Studios Japan tickets over time, so that price patterns the ticket store itself doesn't show can be charted.

## Language

**Visit Date**:
The calendar day a ticket is valid for entry to the park.
_Avoid_: Use date, ticket date

**Snapshot**:
One daily reading of the store's price calendars. A Snapshot belongs to the Japan-time calendar date on which it ran.
_Avoid_: Capture, scrape, run

**Price Observation**:
The price of one product for one Guest Type on one Visit Date, as seen in one Snapshot.
_Avoid_: Price point, record

**Guest Type**:
The kind of guest a price applies to: Adult, Child, Senior, All Ages, or an accessible-admission variant.
_Avoid_: Age category, user type

**Dynamic Pricing**:
A change in the price of the same Visit Date from one Snapshot to a later one.
_Avoid_: Repricing, fluctuation

**Date-Based Pricing**:
The price differing from one Visit Date to another within a single Snapshot.
_Avoid_: Dynamic pricing, variable pricing

**Lead Time**:
The number of days from a Snapshot's date to a Visit Date.
_Avoid_: Days out, days before

**Opening Price**:
The price in the Snapshot where a Visit Date first appears in a product's price calendar. It is unknown for Visit Dates that were already listed in the very first Snapshot.
_Avoid_: First price, initial price

**Final Price**:
The last price observed for a Visit Date before it leaves a product's price calendar.
_Avoid_: Last price, closing price

**Not Listed**:
The state of a Visit Date that is absent from a product's price calendar in a Snapshot, for a reason the store doesn't give.
_Avoid_: Sold out, closed

**Unavailable**:
The state of a Visit Date that appears in a product's price calendar but is marked as not purchasable.
_Avoid_: Sold out
