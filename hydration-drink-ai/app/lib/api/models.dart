/// Data types shared between the API client and the UI.
///
/// Mirrors the backend's shapes rather than inventing new ones, so a change
/// there shows up here as a parse failure instead of a silently wrong screen.
library;

/// One logged drink.
class Entry {
  const Entry({
    required this.id,
    required this.name,
    required this.quantity,
    required this.loggedAt,
    this.drinkId,
    this.source = 'app',
  });

  final String id;
  final String? drinkId;
  final String name;
  final double quantity;
  final DateTime loggedAt;
  final String source;

  static Entry fromJson(Map<String, dynamic> json) => Entry(
        id: json['id'] as String,
        drinkId: json['drink_id'] as String?,
        name: json['name'] as String,
        quantity: (json['quantity'] as num).toDouble(),
        loggedAt: DateTime.parse(json['logged_at'] as String),
        source: json['source'] as String? ?? 'app',
      );
}

/// A drink from the catalog.
class Drink {
  const Drink({
    required this.id,
    required this.name,
    required this.category,
    required this.servingSizeMl,
    required this.isAlcohol,
    this.calories,
    this.caffeineMg,
  });

  final String id;
  final String name;
  final String category;
  final int servingSizeMl;
  final bool isAlcohol;

  /// Null when nobody has sourced it yet. The UI shows nothing rather than a
  /// guess — see the backend's seed loader.
  final double? calories;
  final double? caffeineMg;

  bool get hasNutrition => calories != null;

  static Drink fromJson(Map<String, dynamic> json) => Drink(
        id: json['id'] as String,
        name: json['name'] as String,
        category: json['category'] as String,
        servingSizeMl: json['serving_size_ml'] as int,
        isAlcohol: json['is_alcohol'] as bool,
        calories: (json['calories'] as num?)?.toDouble(),
        caffeineMg: (json['caffeine_mg'] as num?)?.toDouble(),
      );
}

/// Today's entries and totals.
class Today {
  const Today({
    required this.date,
    required this.entries,
    required this.totals,
    required this.categories,
    this.waterTargetMl,
  });

  final String date;
  final List<Entry> entries;
  final Map<String, double> totals;
  final Map<String, double> categories;

  /// Null unless the user opted into giving a weight.
  final int? waterTargetMl;

  static Today fromJson(Map<String, dynamic> json) => Today(
        date: json['date'] as String,
        entries: (json['entries'] as List<dynamic>)
            .map((e) => Entry.fromJson(e as Map<String, dynamic>))
            .toList(),
        totals: _numMap(json['totals']),
        categories: _numMap(json['categories']),
        waterTargetMl: json['water_target_ml'] as int?,
      );
}

/// An event queued for the backend: an add, or a tombstone.
///
/// The client half of the sync model. Entries carry an id generated here, and
/// a removal is a tombstone rather than a decrement, so replaying the queue
/// after a dropped connection cannot double or lose a drink.
class OutboxEvent {
  const OutboxEvent.add({
    required this.id,
    required this.drinkId,
    required this.quantity,
    required this.loggedAt,
  }) : type = 'add';

  const OutboxEvent.remove({required this.id})
      : type = 'remove',
        drinkId = null,
        quantity = 1,
        loggedAt = null;

  final String type;
  final String id;
  final String? drinkId;
  final double quantity;
  final DateTime? loggedAt;

  Map<String, dynamic> toJson() => switch (type) {
        'add' => <String, dynamic>{
            'type': 'add',
            'id': id,
            'drink_id': drinkId,
            'quantity': quantity,
            if (loggedAt != null) 'logged_at': loggedAt!.toUtc().toIso8601String(),
          },
        _ => <String, dynamic>{'type': 'remove', 'id': id},
      };
}

Map<String, double> _numMap(Object? raw) {
  if (raw is! Map) return <String, double>{};
  return raw.map(
    (key, value) => MapEntry(key as String, (value as num).toDouble()),
  );
}
