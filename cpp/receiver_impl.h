/**
 * @file receiver_impl.h
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-10-15
 *
 * @copyright Copyright (c) 2025
 *
 */

#ifndef WIKI_RECEIVER_IMPL_H_
#define WIKI_RECEIVER_IMPL_H_

#include <algorithm>
#include <tuple>

#include "receiver.h"
#include "dict_class.h"

namespace wiki {

class ReceiverImpl : public Receiver {
public:

    /**
     * @brief Construct a new Receiver Impl object
     *
     */
    ReceiverImpl() {
        std::vector<std::string> vals = {"DataEvents", "ItemsExt"};
        //std::vector<std::string> vals = {"P31", "Item"};
        load_dict_list(vals);

        for_each(vals.begin(), vals.end(), [this](std::string& prop){
            dicts[prop] = std::make_shared<DictClass<dict_key, dict_val>>(prop);
        });

        //we do not want to load Items dictionary because we do not expect duplicate values
        dicts["ItemsExt"]->set_load_at_start(false);
    }

    /**
     * @brief Destroy the Receiver Impl object
     *
     */
    virtual ~ReceiverImpl() {
    }

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    virtual bool save() override {
        std::for_each(dicts.begin(), dicts.end(), [](const std::pair<pID, std::shared_ptr<DictClass<dict_key, dict_val>>>& dict) {
                if(dict.second.get()){
                    dict.second->save();
                }
            });

        return true;
    }

    virtual void flush() override {
        std::for_each(dicts.begin(), dicts.end(), [](const std::pair<pID, std::shared_ptr<DictClass<dict_key, dict_val>>>& dict) {
                if(dict.second.get()){
                    dict.second->save(true);
                }
            });
    }

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    virtual bool load() override {
        std::for_each(dicts.begin(), dicts.end(), [](const std::pair<pID, std::shared_ptr<DictClass<dict_key, dict_val>>>& dict) {
                if(dict.second.get()){
                    if(dict.second->get_load_at_start()){
                        dict.second->load();
                    }
                }
            });

        return true;
    }

    /**
     * @brief
     *
     * @param key
     * @param val
     */
    virtual void put_dictionary_value(const dict_key& d_key, const dict_key& key, const dict_val& val) override {
        if(!is_dictionary(d_key)){
            return;
        }

        dicts[d_key]->put(key, val);
    }

private:
    std::map<pID, std::shared_ptr<DictClass<dict_key, dict_val>>> dicts;
};

}
#endif
