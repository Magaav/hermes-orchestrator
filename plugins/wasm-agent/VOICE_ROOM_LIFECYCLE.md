# Shared Voice Room Lifecycle

## Root-Cause Report

1. Another device could be pulled into voice without consent because ordinary
   room sync called `maybeAutoJoinSharedVoice()`, which could call
   `startSharedVoice()` from remote room state. That path allowed remote join or
   incoming-offer evidence to reach `getUserMedia()` without a local Join click.
2. Leave/rejoin could replay stale signaling because `processedSignalIds` is
   local runtime state. Refresh or rejoin reset that set, then the client walked
   the retained room log and could answer old offers or add old ICE from a
   previous membership.
3. One participant leaving could force another participant out because the
   original hangup semantics treated a call as a shared two-device session. A
   remote hangup/leave could collapse broader local voice state instead of only
   closing the peer owned by the leaving remote membership.
4. Presence, membership, and signaling were coupled in the same room event
   stream. Live shared-space presence supplied targets, retained `join` events
   were treated as current voice membership, and signaling processing created
   peer connections from that inferred state.

## Lifecycle Contract

```text
Shared-space presence
  -> online/viewing state only
  -> never starts microphone
  -> never creates RTCPeerConnection

LOCAL_JOIN_REQUEST
  -> getUserMedia()
  -> create local join_epoch
  -> publish voice join
  -> publish voice membership heartbeat
  -> start WebRTC mesh

WebRTC mesh
  -> connect only while local membership is active
  -> connect only to current remote voice memberships
  -> include sender and target epochs on every signal
  -> ignore signals before local join baseline
  -> ignore signals for any other local epoch
  -> close only the peer whose membership left/expired

LOCAL_LEAVE_REQUEST
  -> publish peer hangups and local leave
  -> stop local tracks
  -> close local peers
  -> clear local membership
```

Remote `join`, `membership`, `offer`, `answer`, `ice-candidate`, `mute`,
`hangup`, and `leave` events never call the local Join or Leave path.

## Manual Verification Checklist

- [ ] A joins, B remains outside voice until B clicks Join.
- [ ] B joins, A and B connect and hear each other.
- [ ] A leaves, B stays joined.
- [ ] B leaves, A stays joined.
- [ ] A refreshes/disconnects, B cleans up only A's peer after membership expiry.
- [ ] A clicks Join again, a new epoch is created and voice reconnects.
- [ ] B refreshes/disconnects, A cleans up only B's peer after membership expiry.
- [ ] Both leave and rejoin, new epochs reconnect.
- [ ] Duplicate tabs on one account appear as separate device memberships.
- [ ] Same account on two devices requires Join on each device.
- [ ] Old offers/candidates before rejoin are ignored.
- [ ] Remote disconnect without graceful leave closes only that peer.
- [ ] Rapid join/leave/rejoin ends on the latest epoch only.
- [ ] No remote event can call local Leave.
- [ ] No remote event can call `getUserMedia()`.

## Remaining Risks

- Browser `beforeunload` is not reliable, so remote disconnect cleanup depends
  on the short voice membership heartbeat TTL.
- TURN/STUN reachability still depends on deployment configuration and network
  policy.
- The room log is retained for collaboration history, so epoch and baseline
  checks must remain part of every future voice signal handler.
