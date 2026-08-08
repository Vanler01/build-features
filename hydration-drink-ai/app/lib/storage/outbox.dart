/// The offline queue.
///
/// This is the client half of the backend's sync model, and it exists for the
/// same reason: taps happen when there is no network — on a train, on a plane,
/// in a lift — and they must survive that without becoming duplicates or
/// vanishing.
///
/// Two rules make it work, and both mirror the server:
///
///   * an add carries an id generated **here**, so re-sending it is a no-op
///     rather than a second drink;
///   * a removal is a tombstone against that id, not a decrement, so it
///     commutes — it wins whether it arrives before or after its add.
///
/// Events are only dropped from the queue once the backend has confirmed them.
/// Dropping on send would lose a day's logging to one dropped connection.
library;

import 'dart:convert';

import 'package:uuid/uuid.dart';

import '../api/models.dart';

/// Where the queue is persisted between app launches.
///
/// An interface rather than a concrete store: the real implementation needs a
/// platform channel, which `flutter test` cannot exercise, and untestable
/// wiring in the middle of the sync logic would put the riskiest code beyond
/// reach of the tests.
abstract class OutboxStorage {
  /// Read the raw persisted queue.
  Future<String?> read();

  /// Persist the raw queue.
  Future<void> write(String value);
}

/// In-memory storage. The default for tests, and a usable fallback.
class MemoryOutboxStorage implements OutboxStorage {
  String? _value;

  @override
  Future<String?> read() async => _value;

  @override
  Future<void> write(String value) async => _value = value;
}

/// A queue of entry events waiting to reach the backend.
class Outbox {
  Outbox({OutboxStorage? storage, Uuid? uuid})
      : _storage = storage ?? MemoryOutboxStorage(),
        _uuid = uuid ?? const Uuid();

  final OutboxStorage _storage;
  final Uuid _uuid;
  final List<OutboxEvent> _pending = <OutboxEvent>[];

  /// Events waiting to be sent, oldest first.
  List<OutboxEvent> get pending => List<OutboxEvent>.unmodifiable(_pending);

  int get length => _pending.length;
  bool get isEmpty => _pending.isEmpty;

  /// Queue a drink. Returns the id it was given, which the UI uses to undo.
  Future<String> add(String drinkId, {double quantity = 1, DateTime? at}) async {
    final String id = _uuid.v4();
    _pending.add(
      OutboxEvent.add(
        id: id,
        drinkId: drinkId,
        quantity: quantity,
        loggedAt: at ?? DateTime.now().toUtc(),
      ),
    );
    await _persist();
    return id;
  }

  /// Queue a removal.
  ///
  /// The tombstone is queued even when the matching add is still sitting
  /// unsent in this same queue. Cancelling them out locally would be wrong:
  /// the add may already have reached the backend on a previous attempt whose
  /// response was lost, and then the drink would stay logged forever with
  /// nothing left to remove it.
  Future<void> remove(String entryId) async {
    _pending.add(OutboxEvent.remove(id: entryId));
    await _persist();
  }

  /// Drop events the backend has confirmed.
  ///
  /// Called only after a successful sync. Anything queued *during* the send is
  /// kept, so a tap made mid-request is not silently discarded.
  Future<void> confirm(List<OutboxEvent> sent) async {
    final Set<String> done =
        sent.map((OutboxEvent e) => '${e.type}:${e.id}').toSet();
    _pending.removeWhere((OutboxEvent e) => done.contains('${e.type}:${e.id}'));
    await _persist();
  }

  /// Restore the queue from storage.
  Future<void> load() async {
    final String? raw = await _storage.read();
    if (raw == null || raw.isEmpty) return;

    _pending
      ..clear()
      ..addAll(
        (jsonDecode(raw) as List<dynamic>)
            .map((Object? e) => _eventFromJson(e! as Map<String, dynamic>)),
      );
  }

  Future<void> _persist() async => _storage.write(
        jsonEncode(_pending.map((OutboxEvent e) => e.toJson()).toList()),
      );

  static OutboxEvent _eventFromJson(Map<String, dynamic> json) {
    if (json['type'] == 'remove') {
      return OutboxEvent.remove(id: json['id'] as String);
    }
    final String? at = json['logged_at'] as String?;
    return OutboxEvent.add(
      id: json['id'] as String,
      drinkId: json['drink_id'] as String?,
      quantity: (json['quantity'] as num).toDouble(),
      loggedAt: at == null ? null : DateTime.parse(at),
    );
  }
}
