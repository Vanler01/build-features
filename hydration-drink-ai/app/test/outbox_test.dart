/// The offline queue.
///
/// This is the client half of the sync model, so it is tested against the same
/// properties the backend is: replaying is a no-op, a removal commutes with
/// its add, and nothing leaves the queue until the backend has confirmed it.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:hydration/api/models.dart';
import 'package:hydration/storage/outbox.dart';

void main() {
  group('queueing', () {
    test('an add is queued and given an id', () async {
      final Outbox outbox = Outbox();
      final String id = await outbox.add('water_250');

      expect(id, isNotEmpty);
      expect(outbox.length, 1);
      expect(outbox.pending.single.type, 'add');
    });

    test('ids are unique per tap', () async {
      final Outbox outbox = Outbox();
      final String first = await outbox.add('water_250');
      final String second = await outbox.add('water_250');

      expect(first, isNot(second));
    });

    test('a removal is queued as a tombstone, not a decrement', () async {
      final Outbox outbox = Outbox();
      final String id = await outbox.add('water_250');
      await outbox.remove(id);

      expect(outbox.length, 2);
      expect(outbox.pending.last.type, 'remove');
    });

    test('a removal is kept even when its add is still unsent', () async {
      // Cancelling them out locally would be wrong: the add may already have
      // reached the backend on an attempt whose response was lost.
      final Outbox outbox = Outbox();
      final String id = await outbox.add('water_250');
      await outbox.remove(id);

      expect(outbox.pending.map((OutboxEvent e) => e.type), <String>['add', 'remove']);
    });
  });

  group('confirmation', () {
    test('confirmed events leave the queue', () async {
      final Outbox outbox = Outbox();
      await outbox.add('water_250');
      final List<OutboxEvent> batch = outbox.pending;

      await outbox.confirm(batch);
      expect(outbox.isEmpty, isTrue);
    });

    test('nothing leaves the queue before confirmation', () async {
      // Dropping on send would lose a day's logging to one dropped connection.
      final Outbox outbox = Outbox();
      await outbox.add('water_250');
      final List<OutboxEvent> _ = outbox.pending;

      expect(outbox.length, 1);
    });

    test('a tap made during a send is not discarded', () async {
      final Outbox outbox = Outbox();
      await outbox.add('water_250');
      final List<OutboxEvent> inFlight = outbox.pending;

      await outbox.add('brewed_coffee_240'); // tapped mid-request
      await outbox.confirm(inFlight);

      expect(outbox.length, 1);
      expect(outbox.pending.single.drinkId, 'brewed_coffee_240');
    });

    test('confirming twice is harmless', () async {
      final Outbox outbox = Outbox();
      await outbox.add('water_250');
      final List<OutboxEvent> batch = outbox.pending;

      await outbox.confirm(batch);
      await outbox.confirm(batch);
      expect(outbox.isEmpty, isTrue);
    });
  });

  group('persistence', () {
    test('the queue survives a restart', () async {
      final MemoryOutboxStorage storage = MemoryOutboxStorage();
      final Outbox before = Outbox(storage: storage);
      await before.add('water_250');
      await before.add('brewed_coffee_240');

      final Outbox after = Outbox(storage: storage);
      await after.load();

      expect(after.length, 2);
      expect(after.pending.first.drinkId, 'water_250');
    });

    test('a removal survives a restart as a removal', () async {
      final MemoryOutboxStorage storage = MemoryOutboxStorage();
      final Outbox before = Outbox(storage: storage);
      await before.remove('some-entry-id');

      final Outbox after = Outbox(storage: storage);
      await after.load();

      expect(after.pending.single.type, 'remove');
      expect(after.pending.single.id, 'some-entry-id');
    });

    test('loading from empty storage is not an error', () async {
      final Outbox outbox = Outbox(storage: MemoryOutboxStorage());
      await outbox.load();
      expect(outbox.isEmpty, isTrue);
    });

    test('confirmation is persisted, not just in memory', () async {
      final MemoryOutboxStorage storage = MemoryOutboxStorage();
      final Outbox outbox = Outbox(storage: storage);
      await outbox.add('water_250');
      await outbox.confirm(outbox.pending);

      final Outbox reloaded = Outbox(storage: storage);
      await reloaded.load();
      expect(reloaded.isEmpty, isTrue);
    });
  });

  group('wire format', () {
    test('an add serialises the fields the backend expects', () async {
      final Outbox outbox = Outbox();
      final DateTime at = DateTime.utc(2026, 8, 9, 10, 30);
      await outbox.add('water_250', quantity: 2, at: at);

      final Map<String, dynamic> json = outbox.pending.single.toJson();
      expect(json['type'], 'add');
      expect(json['drink_id'], 'water_250');
      expect(json['quantity'], 2.0);
      expect(json['logged_at'], at.toIso8601String());
    });

    test('a removal carries only a type and an id', () async {
      final Outbox outbox = Outbox();
      await outbox.remove('entry-9');

      expect(outbox.pending.single.toJson(), <String, dynamic>{
        'type': 'remove',
        'id': 'entry-9',
      });
    });

    test('timestamps are sent in UTC', () async {
      // The backend resolves the user's day from its own timezone field; a
      // local-time timestamp would land in the wrong day for half the world.
      final Outbox outbox = Outbox();
      await outbox.add('water_250', at: DateTime.utc(2026, 8, 9, 23));

      expect(outbox.pending.single.toJson()['logged_at'], endsWith('Z'));
    });
  });
}
