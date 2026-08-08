/// Today's drinks: what you've had, and one tap to add more.
///
/// The tap targets here are the app-side echo of the home-screen widget, and
/// they behave the same way on purpose — a tap adds, and an undo is available
/// briefly afterwards. The widget cannot offer anything richer, because the OS
/// gives it a tap and nothing else.
library;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/app_state.dart';

/// Shows today's totals and a grid of quick-add drinks.
class TodayScreen extends StatefulWidget {
  const TodayScreen({
    required this.state,
    this.alcoholUnlocked = false,
    super.key,
  });

  final AppState state;

  /// Alcohol stays hidden until the self-declared age check passes.
  final bool alcoholUnlocked;

  @override
  State<TodayScreen> createState() => _TodayScreenState();
}

class _TodayScreenState extends State<TodayScreen> {
  /// The most recent log, kept so it can be undone.
  ({String entryId, String drinkId, String name})? _lastLogged;

  @override
  void initState() {
    super.initState();
    widget.state.addListener(_onStateChanged);
  }

  @override
  void dispose() {
    widget.state.removeListener(_onStateChanged);
    super.dispose();
  }

  void _onStateChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _log(Drink drink) async {
    final String id = await widget.state.log(drink.id);
    if (!mounted) return;
    setState(() {
      _lastLogged = (entryId: id, drinkId: drink.id, name: drink.name);
    });
  }

  Future<void> _undoLast() async {
    final ({String entryId, String drinkId, String name})? last = _lastLogged;
    if (last == null) return;
    await widget.state.undo(last.entryId, last.drinkId);
    if (!mounted) return;
    setState(() => _lastLogged = null);
  }

  @override
  Widget build(BuildContext context) {
    final AppState state = widget.state;
    final Map<String, double> totals = state.totals;
    final List<Drink> drinks =
        state.visibleCatalog(alcoholUnlocked: widget.alcoholUnlocked);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Today'),
        actions: <Widget>[
          if (state.pendingCount > 0)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Center(
                child: Text(
                  '${state.pendingCount} to sync',
                  key: const Key('pending-badge'),
                ),
              ),
            ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: state.refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: <Widget>[
            if (totals.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Text('Nothing logged yet today.', key: Key('empty-today')),
              )
            else
              for (final MapEntry<String, double> total in totals.entries)
                ListTile(
                  key: Key('total-${total.key}'),
                  title: Text(_nameFor(state, total.key)),
                  trailing: Text(
                    _formatQuantity(total.value),
                    key: Key('count-${total.key}'),
                  ),
                ),
            const Divider(),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: <Widget>[
                for (final Drink drink in drinks)
                  ElevatedButton(
                    key: Key('add-${drink.id}'),
                    onPressed: () => _log(drink),
                    child: Text(drink.name),
                  ),
              ],
            ),
          ],
        ),
      ),
      floatingActionButton: _lastLogged == null
          ? null
          : FloatingActionButton.extended(
              key: const Key('undo-button'),
              onPressed: _undoLast,
              icon: const Icon(Icons.undo),
              label: Text('Undo ${_lastLogged!.name}'),
            ),
    );
  }

  static String _nameFor(AppState state, String key) {
    for (final Drink drink in state.catalog) {
      if (drink.id == key) return drink.name;
    }
    return key; // a custom drink, stored under its own name
  }

  static String _formatQuantity(double value) =>
      value == value.roundToDouble() ? '${value.round()}' : value.toString();
}
