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
        std::vector<std::string> vals = {"P31", "Item"};
        load_dict_list(vals);

        for_each(vals.begin(), vals.end(), [this](std::string& prop){
            dicts[prop] = std::make_shared<DictClass<dict_key, dict_val>>(prop);
        });
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

    /**
     * @brief
     *
     * @return true
     * @return false
     */
    virtual bool load() override {
        std::for_each(dicts.begin(), dicts.end(), [](const std::pair<pID, std::shared_ptr<DictClass<dict_key, dict_val>>>& dict) {
                if(dict.second.get()){
                    dict.second->load();
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
    virtual void put_dictionary_value(const dict_key& key, const dict_val& val) override {
        if(!is_dictionary(key)){
            return;
        }

        //std::cout << "Property: " << key << " [ Type: " << std::get<0>(val) << "] Val: " << std::get<1>(val) << std::endl;
        dicts[key]->put(std::get<1>(val), val);
    }

private:
    std::map<pID, std::shared_ptr<DictClass<dict_key, dict_val>>> dicts;
};

}
#endif
