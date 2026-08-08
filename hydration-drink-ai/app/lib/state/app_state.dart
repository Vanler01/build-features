/// Application state.
///
/// A plain `ChangeNotifier` rather than a state-management package: the app has
/// one screen's worth of state, and a dependency whose behaviour I cannot run
/// on a device is a poor trade for syntax.
///
/// The important behaviour here is optimistic logging. A tap updates the
/// on-screen count immediately and queues the event; the network catches up
/// afterwards. A hydration tracker that spins for a second per tap does not get
/// used, and the outbox makes the optimism safe — nothing is lost if the send
/// fails, and nothing is doubled if it half-succeeded.
library;

import 'package:flutter/foundation.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../storage/outbox.dart';

/// What the app is currently doing, for the UI to render.
enum AppStatus { needsLink, loading, ready, failed }

/// Holds session state and mediates between the UI, the outbox and the API.
class AppState extends ChangeNotifier {
  AppState({required ApiClient api, Outbox? outbox})
      : _api = api,
        _outbox = outbox ?? Outbox();

  final ApiClient _api;
  final Outbox _outbox;

  AppStatus _status = AppStatus.needsLink;
  String? _error;
  Today? _today;
  List<Drink> _catalog = <Drink>[];

  /// Counts applied locally but not yet confirmed by the backend.
  final Map<String, double> _optimistic = <String, double>{};

  AppStatus get status => _status;
  String? get error => _error;
  Today? get today => _today;
  List<Drink> get catalog => _catalog;
  int get pendingCount => _outbox.length;

  /// Drinks the user may log. Alcohol is hidden until the age check passes.
  List<Drink> visibleCatalog({required bool alcoholUnlocked}) =>
      _catalog.where((Drink d) => alcoholUnlocked || !d.isAlcohol).toList();

  /// Today's totals including anything queued but not yet sent.
  ///
  /// Without this the count would visibly jump backwards the moment a refresh
  /// landed before a sync did.
  Map<String, double> get totals {
    final Map<String, double> merged =
        Map<String, double>.from(_today?.totals ?? <String, double>{});
    _optimistic.forEach((String key, double value) {
      merged[key] = (merged[key] ?? 0) + value;
    });
    merged.removeWhere((_, double value) => value <= 0);
    return merged;
  }

  /// Redeem a bot link code and load the first screen.
  Future<void> link(String code) async {
    _set(AppStatus.loading);
    try {
      await _api.redeem(code);
      await refresh();
    } on ApiException catch (e) {
      _error = e.detail;
      _set(AppStatus.failed);
    }
  }

  /// Reload today and the catalog.
  Future<void> refresh() async {
    if (!_api.isLinked) {
      _set(AppStatus.needsLink);
      return;
    }
    _set(AppStatus.loading);
    try {
      _today = await _api.today();
      if (_catalog.isEmpty) _catalog = await _api.catalog();
      _error = null;
      _set(AppStatus.ready);
    } on ApiException catch (e) {
      if (e.isUnauthorized) {
        _api.token = null;
        _set(AppStatus.needsLink);
        return;
      }
      _error = e.detail;
      _set(AppStatus.failed);
    }
  }

  /// Log a drink. Updates the display at once and queues the event.
  Future<String> log(String drinkId, {double quantity = 1}) async {
    final String id = await _outbox.add(drinkId, quantity: quantity);
    _optimistic[drinkId] = (_optimistic[drinkId] ?? 0) + quantity;
    notifyListeners();
    unawaited(flush());
    return id;
  }

  /// Undo a logged drink, by the id `log` returned.
  Future<void> undo(String entryId, String drinkId, {double quantity = 1}) async {
    await _outbox.remove(entryId);
    _optimistic[drinkId] = (_optimistic[drinkId] ?? 0) - quantity;
    notifyListeners();
    unawaited(flush());
  }

  /// Push the queue. Safe to call at any time, including concurrently.
  Future<void> flush() async {
    if (_outbox.isEmpty || !_api.isLinked) return;

    final List<OutboxEvent> batch = _outbox.pending;
    try {
      await _api.sync(batch);
    } on ApiException catch (e) {
      if (e.isUnauthorized) {
        _api.token = null;
        _set(AppStatus.needsLink);
      }
      // Anything else: leave the batch queued and try again later. Losing a
      // day's drinks to one bad response would be far worse than a retry.
      return;
    } on Exception {
      return; // offline; the queue is the point
    }

    await _outbox.confirm(batch);
    // The server is now authoritative, so the local overlay can go.
    _optimistic.clear();
    await refresh();
  }

  void _set(AppStatus status) {
    _status = status;
    notifyListeners();
  }
}

/// Fire-and-forget without tripping the unawaited_futures lint.
void unawaited(Future<void> future) {
  future.ignore();
}
